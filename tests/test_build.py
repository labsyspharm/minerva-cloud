from ruamel.yaml import YAML
import pytest

from cloudformation.cloudformation import operate_on_stack
from ami_builder.build import build_ami

from .fixtures import *  # noqa


yaml = YAML()


# Skip this test for now, as moto does not currently support SSM in
# cloudformation.
@pytest.mark.skip()
def test_ami_build(cf, ssm, efs, ec2, minerva_config):
    # Create the common stack
    operate_on_stack(cf, "create", "common", minerva_config)

    # Test the runner
    config_json = yaml.load(minerva_config)
    build_ami(config_json)
