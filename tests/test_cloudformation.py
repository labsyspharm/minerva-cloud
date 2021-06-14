from os import path
from cloudformation.cloudformation import CloudFormationStack, operate_on_stack


def test_stack_templates():
    for s_name in CloudFormationStack.list_stacks():
        stack = CloudFormationStack.from_name(s_name)
        config_fpath = stack.get_template_path()
        assert path.exists(config_fpath)
        assert path.abspath(config_fpath) == config_fpath
