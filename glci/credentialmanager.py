import os
import ccc.aws
import ccc.gcp
import enum
import logging

from botocore import UNSIGNED
from botocore.config import Config

import ci.util

import boto3
import google.cloud.storage as storage


class CCconfigPrecedence(enum.Enum):
    ALWAYS = 'always'
    PROBE = 'probe'
    NEVER = 'never'

    def equals(self, str):
        return self.value == str


def add_credential_parsing_args(parser):
    parser.add_argument(
        '--use-cc-config',
        default='probe',
        choices=tuple(map(lambda x: x.value, CCconfigPrecedence._member_map_.values())),
        dest='cc_config_auth',
        help='configures if authentication credentials for cloud provers should be obtained from the cc config server',
    )


class CredentialManager():

    _instance = None

    def __init__(self, use_cc_config: CCconfigPrecedence):
        self.use_cc_config_server = False
        self.logger =  logging.getLogger(__name__)

        cc_config_server_available = (os.getenv("SECRETS_SERVER_ENDPOINT") and os.getenv("SECRETS_SERVER_CONCOURSE_CFG_NAME"))
        if (CCconfigPrecedence.ALWAYS.equals(use_cc_config) or
            (CCconfigPrecedence.PROBE.equals(use_cc_config) and cc_config_server_available)):
            self.logger.info("Using cc-config secret server to obtain credentials")
            self.use_cc_config_server = True
        else:
            self.logger.info("Obtaining cloud provider credentials from environment")


    @classmethod
    def get_instance(cls, use_cc_config: CCconfigPrecedence = CCconfigPrecedence.PROBE):
        if cls._instance == None:
            cls._instance = CredentialManager(use_cc_config=use_cc_config)
        return cls._instance

        
    def get_aws_session(self, aws_cfg: str = None, region_name: str = None):
        if self.use_cc_config_server:
            return ccc.aws.session(aws_cfg=aws_cfg, region_name=region_name)
        else:
            print(f'{aws_cfg=}')
            return boto3.Session(profile_name=aws_cfg, region_name=region_name)
        
    
    def get_s3_client(self, aws_cfg: str = None, region_name: str = None):
        return self.get_aws_session(aws_cfg=aws_cfg, region_name=region_name).client('s3')
        
    def get_anonymous_s3_client(self, region_name: str = None):
        return boto3.client('s3', config=Config(signature_version=UNSIGNED), region_name=region_name)
    

    def get_gcp_storage_client(self, gcp_cfg: str):
        storage_client = None

        if self.use_cc_config_server:
            cfg_factory = ci.util.ctx().cfg_factory()
            gcp_cfg = cfg_factory.gcp(gcp_cfg)
            storage_client = ccc.gcp.cloud_storage_client(gcp_cfg)
        else: 
            storage_client = storage.Client(project=gcp_cfg, credentials=None)
        return storage_client