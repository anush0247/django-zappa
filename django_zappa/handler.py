# -*- coding: utf-8 -*-

from __future__ import print_function
from __future__ import unicode_literals

import base64
import datetime
import importlib
import logging
import os

import django
from django.core.wsgi import get_wsgi_application
from django.test.utils import get_runner
from werkzeug.wrappers import Response
from zappa.middleware import ZappaWSGIMiddleware
from zappa.wsgi import common_log, create_wsgi_request

# Django requires settings and an explicit call to setup()
# if being used from inside a python context.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "zappa_settings")

logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.INFO)

ERROR_CODES = [400, 401, 403, 404, 500]


def start(a, b):
    """
    This doesn't matter, but Django's handler requires it.
    """
    return


def get_stage_vars(zappa_settings, api_stage):
    import boto3
    api_name = zappa_settings[api_stage]["lambda_function"]
    client = boto3.client('apigateway', region_name=zappa_settings[api_stage].get('aws_region', 'ap-southeast-1'))
    apis = filter(lambda api: api['name'] == api_name, client.get_rest_apis(limit=500)['items'])
    if len(apis) > 1:
        print('Found multiple apis with name %s. Choosing the first one to import stage_vars' % api_name)
        raise
    elif len(apis) == 0:
        print('No apis found')
        raise
    api_id = apis[0]["id"]
    if not api_id:
        print('Cannot find any api with name %s' % api_name)
        raise
    stage_vars = client.get_stage(restApiId=api_id, stageName=api_stage)['variables']
    return stage_vars


def lambda_handler(event, context, settings_name="zappa_settings"):  # NoQA
    """
    An AWS Lambda function which parses specific API Gateway input into a WSGI request.

    The request get fed it to Django, processes the Django response, and returns that
    back to the API Gateway.
    """
    import json
    if isinstance(event, unicode) or isinstance(event, str):
        print("in the json converter")
        event = json.loads(event)
    time_start = datetime.datetime.now()
    if event.get("function", None):
        stage = event.get("stage", 'alpha')
        try:
            zappa_settings = getattr(importlib.import_module('zappa_deploy'), 'ZAPPA_SETTINGS')
            event["stage_vars"] = get_stage_vars(zappa_settings, stage)
        except ImportError as err:
            print(err)
            raise
    try:
        base64_env_vars = ["AWS_SECRET_ACCESS_KEY"]
        
        for key in event.get('stage_vars', dict()).keys():
            if key.upper() in base64_env_vars:
                os.environ[key.upper()] = base64.b64decode(event['stage_vars'][key])
            else:
                os.environ[key.upper()] = event['stage_vars'][key]
                
        os_env_to_remove = ["AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN"]
        for each_key in os_env_to_remove:
            del os.environ[each_key]
    except:
        logger.error("Error in stage_vars")
    # If in DEBUG mode, log all raw incoming events.
    django.setup()
    from django.conf import settings
    if settings.DEBUG:
        # logger.info('Zappa Event: {}'.format(event))
        pass
    # This is a normal HTTP request
    if event.get('method', None):
        # Create the environment for WSGI and handle the request
        environ = create_wsgi_request(event, script_name=settings.SCRIPT_NAME)

        # We are always on https on Lambda, so tell our wsgi app that.
        environ['HTTPS'] = 'on'
        environ['wsgi.url_scheme'] = 'https'

        wrap_me = get_wsgi_application()
        app = ZappaWSGIMiddleware(wrap_me)

        # Execute the application
        response = Response.from_app(app, environ)
        response.content = response.data

        # Prepare the special dictionary which will be returned to the API GW.
        returnme = {'Content': response.data}

        # Pack the WSGI response into our special dictionary.
        for (header_name, header_value) in response.headers:
            returnme[header_name] = header_value
        returnme['Status'] = response.status_code

        # To ensure correct status codes, we need to
        # pack the response as a deterministic B64 string and raise it
        # as an error to match our APIGW regex.
        # The DOCTYPE ensures that the page still renders in the browser.
        exception = None
        if response.status_code in ERROR_CODES:
            content = u"<!DOCTYPE html>" + unicode(response.status_code) + unicode(
                '<meta charset="utf-8" />') + response.data.encode('utf-8')
            # content = response.data.encode('utf-8')
            b64_content = base64.b64encode(content)
            exception = (b64_content)
        # Internal are changed to become relative redirects
        # so they still work for apps on raw APIGW and on a domain.
        elif 300 <= response.status_code < 400 and response.has_header('Location'):
            location = returnme['Location']
            location = '/' + location.replace("http://zappa/", "")
            exception = location

        # Calculate the total response time,
        # and log it in the Common Log format.
        time_end = datetime.datetime.now()
        delta = time_end - time_start
        response_time_ms = delta.total_seconds() * 1000
        common_log(environ, response, response_time=response_time_ms)

        # Finally, return the response to API Gateway.
        if exception:
            raise Exception(exception)
        else:
            return returnme

    # This is a management command invocation.
    elif event.get('command', None):
        from django.core import management

        # Couldn't figure out how to get the value into stdout with StringIO..
        # Read the log for now. :[]
        management.call_command(*event['command'].split(' '))
        return {}

    elif event.get("Key", None):
        test_case = event["Key"]
        print(test_case)
        TestRunner = get_runner(settings)
        test_runner = TestRunner()
        failures = test_runner.run_tests([test_case])
        if failures:
            raise Exception({"Success": "NOT_OK", "ErrorMsg": "Test Failed"})
        return {"Success": "OK", "ErrorMsg": ""}

    elif event.get("function", None):
        function_split = event.get("function").split(".")
        print(function_split)
        import_str = ".".join(function_split[0:-1])
        function_name = function_split[-1]
        try:
            function = getattr(importlib.import_module(import_str), function_name)
            input_data = event.get("function_input", {})
            return function(**input_data)
        except ImportError as err:
            print(err)
            raise
