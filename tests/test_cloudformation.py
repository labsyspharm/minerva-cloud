from os import path
from cloudformation.cloudformation import Stack


def test_stack_templates():
    for s_name in Stack.list_stacks():
        stack = Stack.from_name(s_name)
        config_fpath = stack.get_template_path()
        assert path.exists(config_fpath)
        assert path.abspath(config_fpath) == config_fpath
