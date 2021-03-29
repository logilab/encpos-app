from elasticsearch import Elasticsearch
from flask import Flask, Blueprint
from dotenv import load_dotenv

api_bp = Blueprint('api_bp', __name__)


def create_app(config_name="dev"):
    """ Create the application """
    app = Flask(__name__)
    if not isinstance(config_name, str):
        from config import config
        app.config.from_object(config)
    else:
        print("Load environment variables for config '%s'" % config_name)
        # It is important to load the .env file before parsing the config file
        import os
        dir_path = os.path.dirname(os.path.realpath(__file__))
        env_filename = os.path.join(dir_path, '..', '%s.env' % config_name)
        load_dotenv(env_filename, verbose=True)
        from config import config
        app.config.from_object(config[config_name])

    app.elasticsearch = Elasticsearch([app.config['ELASTICSEARCH_URL']]) if app.config['ELASTICSEARCH_URL'] else None

    with app.app_context():
        from app.search import api_search_documents
        app.register_blueprint(api_bp)

    return app
