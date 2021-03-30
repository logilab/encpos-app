import json
import pprint
import time

from flask import app, Response, request, current_app

from app import api_bp

def parse_range_parameter():
    _range = None
    _parsed_ranges = []
    for f in request.args.keys():
        if f.startswith('range[') and f.endswith(']'):
            key, ops = (f[len('range['):-1], [op.split(':') for op in request.args[f].split(",")])
            print(key, ops)
            _range = {key: {}}
            for op, value in ops:
                _range[key][op] = value
            _parsed_ranges.append(_range)
    return _parsed_ranges

@api_bp.route('/api/<api_version>/search')
def api_search_documents(api_version):
    start_time = time.time()
    # PARAMETERS
    index = request.args.get("index", None)
    query = request.args.get("query", None)

    # eg. range[year]=gte:1871,lte:1899
    ranges = parse_range_parameter()

    groupby = request.args.get("groupby[field]", None)
    after = request.args.get("page[after]", None)

    if query is None:
        return Response(status=400)

    # if request has pagination parameters
    # add links to the top-level object
    if 'page[number]' in request.args or 'page[size]' in request.args:
        num_page = int(request.args.get('page[number]', 1))
        page_size = min(
            int(current_app.config["SEARCH_RESULT_PER_PAGE"]) + num_page,
            int(request.args.get('page[size]'))
        )
    else:
        num_page = 1
        page_size = int(current_app.config["SEARCH_RESULT_PER_PAGE"])

    # Search, retrieve, filter, sort and paginate objs
    # eg. &sort=-year
    sort_criteriae = None
    if "sort" in request.args:
        sort_criteriae = []
        for criteria in request.args["sort"].split(','):
            if criteria.startswith('-'):
                sort_order = "desc"
                criteria = criteria[1:]
            else:
                sort_order = "asc"
            # criteria = criteria.replace("-", "_")
            sort_criteriae.append({criteria: {"order": sort_order}})

    #def query_index(index, query, range=None, groupby=None, sort_criteriae=None, page=None, page_size=None, after=None):
    if sort_criteriae is None:
        sort_criteriae = []
    if hasattr(current_app, 'elasticsearch'):
        body = {
            "query": {
                "bool": {
                    "must": [
                        {
                            "query_string": {
                                "query": query,
                                "default_operator": "AND"
                            }
                        }
                    ]
                },
            },
            "highlight": {
                "type": "fvh",
                "fields": {
                    "content": {}
                },
                "number_of_fragments": 100,
                "options": {"return_offsets": True}
            },
            "aggregations": {

            },
            "sort": [
                #  {"creation": {"order": "desc"}}
                *sort_criteriae
            ]
        }

        if ranges:
            body["query"]["bool"]['must'].extend([{"range": r} for r in ranges])

        if groupby is not None:
            body["aggregations"] = {
                "items": {
                    "composite": {
                        "sources": [
                            {
                                "item": {
                                    "terms": {
                                        "field": groupby,
                                    },
                                }
                            },
                        ],
                        "size": page_size
                    }
                },
                "type_count": {
                    "cardinality": {
                        "field": "year"
                    }
                }
            }
            body["size"] = 0

            sort_criteriae.reverse()
            for crit in sort_criteriae:
                for crit_name, crit_order in crit.items():
                    source = {
                        crit_name: {
                            "terms": {
                                "field": crit_name,
                                **crit_order},
                        }
                    }
                    body["aggregations"]["items"]["composite"]["sources"].insert(0, source)

            if after is not None:
                sources_keys = [list(s.keys())[0] for s in body["aggregations"]["items"]["composite"]["sources"]]
                body["aggregations"]["items"]["composite"]["after"] = {key: value for key, value in
                                                                       zip(sources_keys, after.split(','))}
                print(sources_keys, after, {key: value for key, value in zip(sources_keys, after.split(','))})

        if page_size is not None:
            if num_page is None or groupby is not None:
                page = 0
            else:
                page = num_page - 1  # is it correct ?
            body["from"] = page * page_size
            body["size"] = page_size
        else:
            body["from"] = 0 * page_size
            body["size"] = page_size
            # print("WARNING: /!\ for debug purposes the query size is limited to", body["size"])
        try:
            if index is None or len(index) == 0:
                index = current_app.config["DOCUMENT_INDEX"]

            pprint.pprint(body)
            # perform the search
            search_result = current_app.elasticsearch.search(index=index, doc_type="_doc", body=body)

            results = []
            for h in search_result['hits']['hits']:
                fields = h.get('_source')
                fields.pop("content")
                fields['dts_url'] = f"{current_app.config['DTS_URL']}/document?id={h['_id']}"
                results.append({
                    "id": h['_id'],
                    "score": h['_score'],
                    "fields": fields,
                    "highlight": h.get('highlight')
                })

            count = search_result['hits']['total']

            # print(body, len(results), search['hits']['total'], index)
            # pprint.pprint(search)
            if 'aggregations' in search_result:
                after_key = None
                buckets = search_result["aggregations"]["items"]["buckets"]

                # grab the after_key returned by ES for future queries
                if "after_key" in search_result["aggregations"]["items"]:
                    after_key = search_result["aggregations"]["items"]["after_key"]
                print("aggregations: {0} buckets; after_key: {1}".format(len(buckets), after_key))
                # pprint.pprint(buckets)
                count = search_result["aggregations"]["type_count"]["value"]
                r = {
                    "data": results,
                    "buckets": buckets,
                    "after_key": after_key,
                    "total-count": count
                }
            else:
                r = {
                    "data": results,
                    "total-count": count
                }

            r["duration"] = float('%.4f' % (time.time() - start_time))

        except Exception as e:
            return Response(str(e), status=400)

    return Response(
        json.dumps(r, indent=2, ensure_ascii=False),
        status=200,
        content_type="application/json; charset=utf-8",
        headers={
            "Access-Control-Allow-Origin": "*",
            # "Access-Control-Allow-Credentials": "true"
        }
    )
