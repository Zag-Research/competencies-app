"""WSGI entry point for production (Apache + mod_wsgi).

Point Apache at this file:

    WSGIScriptAlias / /var/www/competencies-app/wsgi.py

It exposes `application`, the Flask app mod_wsgi looks for by name. Development does
not use this file at all: run `flask --app app run --debug` instead. Set APP_ENV,
SECRET_KEY, and (if the database is not beside the code) DB_PATH in the server
environment before this imports. See DEPLOYMENT.md.
"""
import sys

path = '/home/dmason/studio'

if path not in sys.path:
    sys.path.append(path)
    #print(sys.path,file=sys.stderr)

from app import app as application
