---
title: 'Authentication'

layout: null
---

Minerva API uses Amazon Cognito for authentication. Clients must authenticate using username and password to obtain an id token for the user.
It's recommended to use a Cognito client library, such as amazon-cognito-identity-js.

Id token must be included in HTTP request headers with each request to Minerva API.
```Authorization: Bearer ID_TOKEN```
### Example (Javascript)

```javascript
import {
  CognitoUserPool,
  AuthenticationDetails,
  CognitoUser
} from 'amazon-cognito-identity-js';

const minervaUserPool = new CognitoUserPool({
    UserPoolId: 'USER_POOL_ID',
    ClientId: 'CLIENT_ID'
});

const cognitoUser = new CognitoUser({
    Username: 'USER_NAME',
    Pool: minervaUserPool
});

const authenticationDetails = new AuthenticationDetails({
    Username: 'USER_NAME',
    Password: 'PASSWORD'
});

cognitoUser.authenticateUser(authenticationDetails, {
    onSuccess: result => success(result),
    onFailure: err => fail(err)
});

```
### Response

```javascript
{
    "AuthenticationResult": {
        "AccessToken":"ACCESS_TOKEN",
        "ExpiresIn":36000,
        "IdToken":"ID_TOKEN",
        "RefreshToken":"REFRESH_TOKEN",
        "TokenType":"Bearer"
    },
    "ChallengeParameters":{}
}
```
