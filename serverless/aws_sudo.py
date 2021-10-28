#!/usr/bin/env python

import os
import click
import boto3
import inflection

from typing import Optional


@click.group()
def main():
    """AWS SUDO acquirer.

    Promote your current terminal session to use SUDO credentials. To use, run these
    commands in back quotes:

        `aws_sudo <cmd> [options]`

    so that the output will be applied as commends (export and unset, specifically).
    """


CREDENTIAL_VARS = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"]


@main.command()
@click.option(
    "--arn",
    help=(
        "Specify an ARN. The same as setting the AWS_SUDO_ROLE_ARN environmnet "
        "variable. If given, this will override the environment variable."
    ),
)
def acquire(arn: Optional[str]):
    """Aquire SUDO privileges.

    This requires that the AWS_SUDO_RULE_ARN environment variable be set. If the
    system was using environment variables they will be lost. It is recommended that
    the credentials file be used for standard credentials.
    """
    if not arn:
        arn = os.environ.get("AWS_SUDO_ROLE_ARN")
        assert arn, "AWS_SUDO_ROLE_ARN environment variable must be set or --arn used."

    sudo_params = boto3.client("sts").assume_role(RoleArn=arn, RoleSessionName="SUDO")

    for cred_name, cred_value in sudo_params["Credentials"].items():
        cred_var = f"AWS_{inflection.underscore(cred_name).upper()}"
        if cred_var not in CREDENTIAL_VARS:
            continue
        print(f"export {cred_var}={cred_value}")


@main.command()
def release():
    """Clear the AWS credential environment variables."""
    for cred_var in CREDENTIAL_VARS:
        print(f"unset {cred_var}")


if __name__ == "__main__":
    main()
