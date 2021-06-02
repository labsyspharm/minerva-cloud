import moto
from os import path
from click.testing import CliRunner

from cloudformation.cloudformation import create
from ami_builder.build import build_ami


@moto.mock_ec2
@moto.mock_ssm
@moto.mock_cloudformation
def test_ami_build():
    config_test_path = path.join(path.dirname(__file__),
                                 'minerva-config.example.yml')
    runner = CliRunner()
    runner.invoke(create, ['test-stack', config_test_path])
    result = runner.invoke(build_ami, [config_test_path])
    assert result.exit_code == 0, result
