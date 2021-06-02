import click

from ami_builder import build
from cloudformation import cloudformation


@click.group()
def minerva_cloud():
    """This CLI is used to manage and monitor the Minerva cloud architecture.

    Minerva is AWS native, and this CLI allows you to deploy new Minerva stacks
    and manage the serverless APIs, and similar.
    """


minerva_cloud.add_command(build.ami)
minerva_cloud.add_command(cloudformation.cloudformation)
