from __future__ import absolute_import

import os

from .zappa_command import ZappaCommand


class Command(ZappaCommand):
    can_import_settings = True
    requires_system_checks = False

    help = '''Update the the lambda package for a given Zappa deployment.'''

    def add_arguments(self, parser):
        parser.add_argument('environment', nargs='+', type=str)
        parser.add_argument('--zip',
                            dest='zip',
                            default=None,
                            help='Use a supplied zip file')

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

        iam = self.zappa.boto_session.client('iam')

        # Create the role if needed
        response = iam.get_role(
            RoleName=self.zappa.role_name
        )

        self.zappa.credentials_arn = response["Role"]["Arn"]

        # Register the Lambda function with that zip as the source
        # You'll also need to define the path to your lambda_handler code.

        self.lambda_name += "_test"
        from botocore.exceptions import ClientError
        try:
            client = self.zappa.boto_session.client('lambda')
            response = client.get_function(
                FunctionName=self.lambda_name,
                Qualifier='$LATEST'
            )
            lambda_arn = self.zappa.update_lambda_function(self.s3_bucket_name, self.zip_path, self.lambda_name)
        except ClientError as err:
            lambda_arn = self.zappa.create_lambda_function(bucket=self.s3_bucket_name,
                                                           s3_key=self.zip_path,
                                                           function_name=self.lambda_name,
                                                           handler='handler.lambda_handler',
                                                           vpc_config=self.vpc_config,
                                                           memory_size=self.memory_size,
                                                           timeout=self.timeout)

        # Remove the uploaded zip from S3, because it is now registered..
        self.zappa.remove_from_s3(self.zip_path, self.s3_bucket_name)

        # Finally, delete the local copy our zip package
        if self.zappa_settings[self.api_stage].get('delete_zip', True) and not options['zip']:
            os.remove(self.zip_path)

        # Remove the local settings
        self.remove_s3_local_settings()

        print("Your updated Zappa deployment is live!")

        return
