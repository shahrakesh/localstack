import sys
import types
import logging
import traceback
from moto.s3 import models as s3_models
from moto.s3 import responses as s3_responses
from moto.server import main as moto_main
from localstack import config
from localstack.constants import DEFAULT_PORT_S3_BACKEND
from localstack.utils.aws import aws_stack
from localstack.utils.common import wait_for_port_open
from localstack.services.infra import (
    get_service_protocol, start_proxy_for_service, do_run)
from localstack.utils.bootstrap import setup_logging

LOG = logging.getLogger(__name__)

# max file size for S3 objects (in MB)
S3_MAX_FILE_SIZE_MB = 2048


def check_s3(expect_shutdown=False, print_error=False):
    out = None
    try:
        # wait for port to be opened
        wait_for_port_open(DEFAULT_PORT_S3_BACKEND)
        # check S3
        out = aws_stack.connect_to_service(service_name='s3').list_buckets()
    except Exception as e:
        if print_error:
            LOG.error('S3 health check failed: %s %s' % (e, traceback.format_exc()))
    if expect_shutdown:
        assert out is None
    else:
        assert isinstance(out['Buckets'], list)


def start_s3(port=None, backend_port=None, asynchronous=None, update_listener=None):
    port = port or config.PORT_S3
    backend_port = DEFAULT_PORT_S3_BACKEND
    cmd = '%s "%s" s3 -p %s -H 0.0.0.0' % (sys.executable, __file__, backend_port)
    print('Starting mock S3 (%s port %s)...' % (get_service_protocol(), port))
    start_proxy_for_service('s3', port, backend_port, update_listener)
    env_vars = {'PYTHONPATH': ':'.join(sys.path)}
    return do_run(cmd, asynchronous, env_vars=env_vars)


def apply_patches():
    s3_models.DEFAULT_KEY_BUFFER_SIZE = S3_MAX_FILE_SIZE_MB * 1024 * 1024

    def init(self, name, value, storage='STANDARD', etag=None,
            is_versioned=False, version_id=0, max_buffer_size=None, *args, **kwargs):
        return original_init(self, name, value, storage=storage, etag=etag, is_versioned=is_versioned,
            version_id=version_id, max_buffer_size=s3_models.DEFAULT_KEY_BUFFER_SIZE, *args, **kwargs)

    original_init = s3_models.FakeKey.__init__
    s3_models.FakeKey.__init__ = init

    def s3_key_response_post(self, request, body, bucket_name, query, key_name, *args, **kwargs):
        result = s3_key_response_post_orig(request, body, bucket_name, query, key_name, *args, **kwargs)
        if query.get('uploadId'):
            # fix for https://github.com/localstack/localstack/issues/1733
            key = self.backend.get_key(bucket_name, key_name)
            acl = self._acl_from_headers(request.headers) or self.backend.get_bucket(bucket_name).acl
            key.set_acl(acl)
        return result

    s3_key_response_post_orig = s3_responses.S3ResponseInstance._key_response_post
    s3_responses.S3ResponseInstance._key_response_post = types.MethodType(
        s3_key_response_post, s3_responses.S3ResponseInstance)


def main():
    setup_logging()
    # patch moto implementation
    apply_patches()
    # start API
    sys.exit(moto_main())


if __name__ == '__main__':
    main()
