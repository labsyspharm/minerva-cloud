"""
Custom lambda authorizer for API Gateway

Reads Cognito IdToken from authorization-header, and decodes and validates it.
The decoded token contains principalId (uuid) of the user, which is forwarded to lambda handlers.

Public (guest) usage of API:
Unauthenticated consumers of the API should send "Anonymous" in the authorization header.
This will be resolved into principalId: 00000000-0000-0000-0000-000000000000
Unauthenticated users are allowed to access only a selected set of endpoints.

The code is heavily based on the Amazon Custom Authorizer Blueprints for AWS Lambda
https://github.com/awslabs/aws-apigateway-lambda-authorizer-blueprints

"""
import re
import os
import boto3
import json
import time
import urllib.request
from jose import jwk, jwt
from jose.utils import base64url_decode

REGION = os.environ['AWS_REGION']
STACK_PREFIX = os.environ['STACK_PREFIX']
STAGE = os.environ['STAGE']

ssm = boto3.client('ssm')
parameters_response = ssm.get_parameters(
    Names=[
        '/{}/{}/common/CognitoUserPoolARN'.format(STACK_PREFIX, STAGE)
    ]
)

def get_value(name):
    for p in parameters_response['Parameters']:
        if p['Name'].endswith(name):
            return p['Value']
    raise ValueError('Value not found for Parameter ' + name)


userpool_arn = get_value('CognitoUserPoolARN')
userpool_id = userpool_arn.split('/')[-1]
#app_client_id = '<ENTER APP CLIENT ID HERE>'
keys_url = 'https://cognito-idp.{}.amazonaws.com/{}/.well-known/jwks.json'.format(REGION, userpool_id)
# instead of re-downloading the public keys every time
# we download them only on cold start
# https://aws.amazon.com/blogs/compute/container-reuse-in-lambda/
with urllib.request.urlopen(keys_url) as f:
    response = f.read()
keys = json.loads(response.decode('utf-8'))['keys']

def decode(token):
    bearer_prefix = "Bearer "
    if bearer_prefix in token:
        token = token[len(bearer_prefix):]
    # get the kid from the headers prior to verification
    headers = jwt.get_unverified_headers(token)
    kid = headers['kid']
    # search for the kid in the downloaded public keys
    key_index = -1
    for i in range(len(keys)):
        if kid == keys[i]['kid']:
            key_index = i
            break
    if key_index == -1:
        raise ValueError('Public key not found in jwks.json')
    # construct the public key
    public_key = jwk.construct(keys[key_index])
    # get the last two sections of the token,
    # message and signature (encoded in base64)
    message, encoded_signature = str(token).rsplit('.', 1)
    # decode the signature
    decoded_signature = base64url_decode(encoded_signature.encode('utf-8'))
    # verify the signature
    if not public_key.verify(message.encode("utf8"), decoded_signature):
        raise ValueError('Signature verification failed')
    # since we passed the verification, we can now safely
    # use the unverified claims
    claims = jwt.get_unverified_claims(token)
    # additionally we can verify the token expiration
    if time.time() > claims['exp']:
        raise ValueError('Token is expired')
    # and the Audience  (use claims['client_id'] if verifying an access token)
    #if claims['aud'] != app_client_id:
    #    print('Token was not issued for this audience')
    #    return False
    # now we can use the claims
    return claims


class Handler:

    def authorize_request(self, event, context):
        anonymous = False
        token = None
        if "authorizationToken" in event:
            token = event['authorizationToken']

        if token == 'Anonymous' or token == 'Bearer Anonymous':
            anonymous = True
            principal_id = '00000000-0000-0000-0000-000000000000'
        else:
            """validate the incoming token"""
            """and produce the principal user identifier associated with the token"""
            try:
                res = decode(token)
                if res is False:
                    raise Exception('Unauthorized')

                principal_id = res['sub']
            except Exception as e:
                raise ValueError('Unauthorized - Invalid token')

        """if the token is valid, a policy must be generated which will allow or deny access to the client"""

        """if access is denied, the client will recieve a 403 Access Denied response"""
        """if access is allowed, API Gateway will proceed with the backend integration configured on the method that was called"""

        """this function must generate a policy that is associated with the recognized principal user identifier."""
        """depending on your use case, you might store policies in a DB, or generate them on the fly"""

        """keep in mind, the policy is cached for 5 minutes by default (TTL is configurable in the authorizer)"""
        """and will apply to subsequent calls to any method/resource in the RestApi"""
        """made with the same token"""

        tmp = event['methodArn'].split(':')
        apiGatewayArnTmp = tmp[5].split('/')
        awsAccountId = tmp[4]

        policy = AuthPolicy(principal_id, awsAccountId)
        policy.restApiId = apiGatewayArnTmp[0]
        policy.region = tmp[3]
        policy.stage = apiGatewayArnTmp[1]

        if anonymous:
            policy.allowMethod(HttpVerb.GET, "/image/*")
            policy.allowMethod(HttpVerb.GET, "/repository")
            policy.allowMethod(HttpVerb.GET, "/repository/*")
            policy.allowMethod(HttpVerb.GET, "/image/*/dimensions")
            policy.allowMethod(HttpVerb.GET, "/authtest")
        else:
            policy.allowAllMethods()

        # Finally, build the policy
        response = policy.build()

        # new! -- add additional key-value pairs associated with the authenticated principal
        # these are made available by APIGW like so: $context.authorizer.<key>
        # additional context is cached
        context = {
            # APIGW will not accept arrays or maps, have to use a string
            'anonymous': anonymous
        }
        response['context'] = context
        return response

    def test_authorization(self, event, context):
        print("Test authorization - auth success")
        print(event)
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Credentials': 'true'
            },
            'body': json.dumps(event)
        }


class HttpVerb:
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    HEAD = "HEAD"
    DELETE = "DELETE"
    OPTIONS = "OPTIONS"
    ALL = "*"


class AuthPolicy(object):
    awsAccountId = ""
    """The AWS account id the policy will be generated for. This is used to create the method ARNs."""
    principalId = ""
    """The principal used for the policy, this should be a unique identifier for the end user."""
    version = "2012-10-17"
    """The policy version used for the evaluation. This should always be '2012-10-17'"""
    pathRegex = "^[/.a-zA-Z0-9-\*]+$"
    """The regular expression used to validate resource paths for the policy"""

    """these are the internal lists of allowed and denied methods. These are lists
    of objects and each object has 2 properties: A resource ARN and a nullable
    conditions statement.
    the build method processes these lists and generates the approriate
    statements for the final policy"""
    allowMethods = []
    denyMethods = []

    restApiId = "*"
    """The API Gateway API id. By default this is set to '*'"""
    region = "*"
    """The region where the API is deployed. By default this is set to '*'"""
    stage = "*"
    """The name of the stage used in the policy. By default this is set to '*'"""

    def __init__(self, principal, awsAccountId):
        self.awsAccountId = awsAccountId
        self.principalId = principal
        self.allowMethods = []
        self.denyMethods = []

    def _addMethod(self, effect, verb, resource, conditions):
        """Adds a method to the internal lists of allowed or denied methods. Each object in
        the internal list contains a resource ARN and a condition statement. The condition
        statement can be null."""
        if verb != "*" and not hasattr(HttpVerb, verb):
            raise NameError("Invalid HTTP verb " + verb + ". Allowed verbs in HttpVerb class")
        resourcePattern = re.compile(self.pathRegex)
        if not resourcePattern.match(resource):
            raise NameError("Invalid resource path: " + resource + ". Path should match " + self.pathRegex)

        if resource[:1] == "/":
            resource = resource[1:]

        resourceArn = ("arn:aws:execute-api:" +
                       self.region + ":" +
                       self.awsAccountId + ":" +
                       self.restApiId + "/" +
                       self.stage + "/" +
                       verb + "/" +
                       resource)

        if effect.lower() == "allow":
            self.allowMethods.append({
                'resourceArn': resourceArn,
                'conditions': conditions
            })
        elif effect.lower() == "deny":
            self.denyMethods.append({
                'resourceArn': resourceArn,
                'conditions': conditions
            })

    def _getEmptyStatement(self, effect):
        """Returns an empty statement object prepopulated with the correct action and the
        desired effect."""
        statement = {
            'Action': 'execute-api:Invoke',
            'Effect': effect[:1].upper() + effect[1:].lower(),
            'Resource': []
        }

        return statement

    def _getStatementForEffect(self, effect, methods):
        """This function loops over an array of objects containing a resourceArn and
        conditions statement and generates the array of statements for the policy."""
        statements = []

        if len(methods) > 0:
            statement = self._getEmptyStatement(effect)

            for curMethod in methods:
                if curMethod['conditions'] is None or len(curMethod['conditions']) == 0:
                    statement['Resource'].append(curMethod['resourceArn'])
                else:
                    conditionalStatement = self._getEmptyStatement(effect)
                    conditionalStatement['Resource'].append(curMethod['resourceArn'])
                    conditionalStatement['Condition'] = curMethod['conditions']
                    statements.append(conditionalStatement)

            statements.append(statement)

        return statements

    def allowAllMethods(self):
        """Adds a '*' allow to the policy to authorize access to all methods of an API"""
        self._addMethod("Allow", HttpVerb.ALL, "*", [])

    def denyAllMethods(self):
        """Adds a '*' allow to the policy to deny access to all methods of an API"""
        self._addMethod("Deny", HttpVerb.ALL, "*", [])

    def allowMethod(self, verb, resource):
        """Adds an API Gateway method (Http verb + Resource path) to the list of allowed
        methods for the policy"""
        self._addMethod("Allow", verb, resource, [])

    def denyMethod(self, verb, resource):
        """Adds an API Gateway method (Http verb + Resource path) to the list of denied
        methods for the policy"""
        self._addMethod("Deny", verb, resource, [])

    def allowMethodWithConditions(self, verb, resource, conditions):
        """Adds an API Gateway method (Http verb + Resource path) to the list of allowed
        methods and includes a condition for the policy statement. More on AWS policy
        conditions here: http://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements.html#Condition"""
        self._addMethod("Allow", verb, resource, conditions)

    def denyMethodWithConditions(self, verb, resource, conditions):
        """Adds an API Gateway method (Http verb + Resource path) to the list of denied
        methods and includes a condition for the policy statement. More on AWS policy
        conditions here: http://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements.html#Condition"""
        self._addMethod("Deny", verb, resource, conditions)

    def build(self):
        """Generates the policy document based on the internal lists of allowed and denied
        conditions. This will generate a policy with two main statements for the effect:
        one statement for Allow and one statement for Deny.
        Methods that includes conditions will have their own statement in the policy."""
        if ((self.allowMethods is None or len(self.allowMethods) == 0) and
                (self.denyMethods is None or len(self.denyMethods) == 0)):
            raise NameError("No statements defined for the policy")

        policy = {
            'principalId': self.principalId,
            'policyDocument': {
                'Version': self.version,
                'Statement': []
            }
        }

        policy['policyDocument']['Statement'].extend(self._getStatementForEffect("Allow", self.allowMethods))
        policy['policyDocument']['Statement'].extend(self._getStatementForEffect("Deny", self.denyMethods))

        return policy


handler = Handler()
authorize_request = handler.authorize_request
test_authorization = handler.test_authorization
