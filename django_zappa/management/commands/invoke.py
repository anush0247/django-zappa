from __future__ import absolute_import

import base64
import json
import boto3

from zappa.zappa import Zappa

from .zappa_command import ZappaCommand


class Command(ZappaCommand):
    can_import_settings = True
    requires_system_checks = False

    help = '''Invoke a management command in a remote Zappa environment.'''

    def add_arguments(self, parser):
        parser.add_argument('environment', nargs='+', type=str)

    def handle(self, *args, **options):
        """
        Execute the command.

        """

        # Load the settings
        self.require_settings(args, options)

        # Load your AWS credentials from ~/.aws/credentials
        self.load_credentials()
        client = boto3.client('apigateway')
        apis = filter(lambda api: api['name'] == self.api_name, client.get_rest_apis(limit=500)['items'])
        if len(apis) > 1:
            self.stdout.write(self.style.WARN(
                'Found multiple apis with name %s. Choosing the first one to import stage_vars' % self.api_name))
        api_id = apis[0]['id']
        if not api_id:
            self.stdout.write(self.style.ERROR('Cannot find any api with name %s' % self.api_name))
            raise
        stage_vars = client.get_stage(restApiId=api_id, stageName=self.api_stage)['variables']
        # Invoke it!
        self.stdout.write(self.style.SUCCESS(
            "Getting stage variables from %s stage of api %s with id %s" % (self.api_stage, self.api_name, api_id)))
        command = {"command": ' '.join(options['environment'][1:]), 'stage_vars': stage_vars}
        response = self.zappa.invoke_lambda_function(
            self.lambda_name, json.dumps(command), invocation_type='RequestResponse')

        if 'LogResult' in response:
            print(base64.b64decode(response['LogResult']))
        else:
            print(response)
            import pdb
            pdb.set_trace()

        return
