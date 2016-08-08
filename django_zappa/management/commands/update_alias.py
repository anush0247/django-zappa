from __future__ import absolute_import
from django.core.management.base import BaseCommand
import os
from zappa.zappa import Zappa
from .zappa_command import ZappaCommand


class CustomZappa(Zappa):
    def __init__(self):
        super(CustomZappa, self).__init__()

    def get_or_create_lambda_function_alias(self, function_name, alias_name):
        client = self.boto_session.client('lambda')

        versions_response = client.list_versions_by_function(FunctionName=function_name)
        available_versions_list = []
        for version in versions_response['Versions']:
            available_versions_list.append(version['Version'])
        print("----- All Available Versions ------")
        print versions_response
        aliases_response = client.list_aliases(FunctionName=function_name)
        aliased_versions_list = []
        for alias in aliases_response['Aliases']:
            aliased_versions_list.append(alias['FunctionVersion'])
        untagged_versions = set(available_versions_list) - set(aliased_versions_list) - {'$LATEST'}
        print("Versions that are not aliased", untagged_versions)
        for version in untagged_versions:
            print("Deleting Untagged Versions")
            print(client.delete_function(FunctionName=function_name, Qualifier=version))

        from botocore.exceptions import ClientError
        try:
            response = client.get_alias(
                FunctionName=function_name,
                Name=alias_name
            )
        except ClientError as err:

            response = client.publish_version(
                FunctionName=function_name,
                Description='publish description'
            )

            function_version = response["Version"]

            response = client.create_alias(
                FunctionName=function_name,
                Name=alias_name,
                FunctionVersion=function_version,
                Description='alias description'
            )

        return response["AliasArn"]

    def update_lambda_function(self, bucket, s3_key, function_name, publish=True, alias_name="$LATEST"):
        print "updating function alias_name : %s" % alias_name

        if alias_name != "$LATEST":
            self.get_or_create_lambda_function_alias(function_name, alias_name)
        return super(CustomZappa, self).update_lambda_function(bucket, s3_key, function_name, publish=False)


class Command(ZappaCommand):
    can_import_settings = True
    requires_system_checks = False

    help = '''Update the the lambda package for a given Zappa deployment.'''

    def __init__(self, *args, **kwargs):
        super(ZappaCommand, self).__init__(*args, **kwargs)
        self.zappa = CustomZappa()

    def add_arguments(self, parser):
        parser.add_argument('environment', nargs='+', type=str)
        parser.add_argument('--zip',
                            dest='zip',
                            default=None,
                            help='Use a supplied zip file')
        parser.add_argument('--alias',
                            dest='alias',
                            default='test',
                            help='alias name for the zappa lambda function')

    def handle(self, *args, **options):  # NoQA
        """
        Execute the command.

        """

        # Load the settings
        self.require_settings(args, options)

        # Load your AWS credentials from ~/.aws/credentials
        self.load_credentials()

        # Get the Django settings file
        self.get_django_settings_file()

        # Create the Lambda Zip,
        # or used the supplied zip file.
        if not options['zip']:
            self.create_package()
        else:
            self.zip_path = options['zip']

        # Upload it to S3
        self.zappa.upload_to_s3(self.zip_path, self.s3_bucket_name)

        # Register the Lambda function with that zip as the source
        # You'll also need to define the path to your lambda_handler code.
        lambda_arn = self.zappa.update_lambda_function(self.s3_bucket_name, self.zip_path, self.lambda_name,
                                                       alias_name=options['alias'])

        # Remove the uploaded zip from S3, because it is now registered..
        self.zappa.remove_from_s3(self.zip_path, self.s3_bucket_name)

        # Finally, delete the local copy our zip package
        if self.zappa_settings[self.api_stage].get('delete_zip', True) and not options['zip']:
            os.remove(self.zip_path)

        # Remove the local settings
        self.remove_s3_local_settings()

        print("Your updated Zappa deployment is live!")

        return
