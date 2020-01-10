class EventBuilder:
    def __init__(self):
        self.event = {
            "requestContext": {
                "authorizer": {
                    "claims": {
                        "cognito:username": "d9e8cac0-5b08-43d6-84fb-8303447783a6"
                    }
                }
            }
        }

    def cognito_user(self, user_uuid):
        self.event["requestContext"]["authorizer"]["claims"]["cognito:username"] = user_uuid
        return self

    def body(self, body):
        self.event["body"] = body
        return self

    def path_parameters(self, parameters):
        if "pathParameters" not in self.event:
            self.event["pathParameters"] = {}

        for key, value in parameters.items():
            self.event["pathParameters"][key] = value

        return self

    def build(self):
        return self.event