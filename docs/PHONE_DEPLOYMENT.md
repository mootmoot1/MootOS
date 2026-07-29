# MootOS Phone Deployment Checklist

This checklist deploys MootOS as one private Railway service connected to GitHub.

## Repository requirements

The deployment branch includes:

- `railway.toml` with the FastAPI start command
- Public `/health` endpoint
- Password login and signed sessions
- Automatic SQLite path selection for an attached Railway volume
- Web-app manifest for adding MootOS to a phone Home Screen

## Create the Railway service

1. Sign in to Railway and create a new project.
2. Choose **Deploy from GitHub repo**.
3. Connect GitHub if Railway asks.
4. Select `mootmoot1/MootOS`.
5. Set the deployment branch to `main`.
6. Choose **Add variables** before the first public deployment.

## Add private variables

Add these service variables in Railway. Never paste their real values into GitHub.

```text
AI_PROVIDER=openai
OPENAI_API_KEY=<your real OpenAI API key>
OPENAI_MODEL=gpt-5-mini
MOOTOS_PASSWORD=<a strong private password>
MOOTOS_SESSION_SECRET=<a long random secret unrelated to the password>
```

A session secret can be generated on a trusted device with a password manager or a random-secret generator. It should be substantially longer than the login password.

Railway automatically provides `PORT`, and `railway.toml` starts Uvicorn on that port.

## Add persistent storage

1. Add a Railway volume to the MootOS service.
2. Set its mount path to:

```text
/data
```

Railway provides `RAILWAY_VOLUME_MOUNT_PATH` automatically. MootOS then stores its SQLite database at:

```text
/data/mootos.db
```

Keep the service at one replica while SQLite is in use.

## Deploy and verify

1. Review Railway's staged changes and deploy.
2. Wait for the deployment to pass the `/health` check.
3. Generate a public Railway domain for the service.
4. Open the domain. It should redirect to the MootOS login page.
5. Confirm the wrong password is rejected.
6. Sign in with `MOOTOS_PASSWORD`.
7. Create a test conversation and memory.
8. Redeploy the service once and confirm the conversation remains after restart.

## Put MootOS on an iPhone Home Screen

1. Open the Railway domain in Safari.
2. Sign in.
3. Tap Safari's **Share** button.
4. Tap **Add to Home Screen**.
5. Name it `MootOS` and add it.

The new icon opens the `/chat` experience in a standalone browser window.

## Normal development after deployment

1. Moot requests a change from ChatGPT.
2. ChatGPT works on a feature branch and opens a pull request.
3. GitHub Actions tests the change.
4. Moot reviews the plain-English explanation and tests when necessary.
5. Moot explicitly approves the merge.
6. The merge reaches `main`.
7. Railway automatically builds and deploys the updated `main` branch.

No phone terminal commands are required for this normal workflow.

## Recovery notes

- If login stops working, change `MOOTOS_PASSWORD` in Railway and redeploy.
- If all sessions must be invalidated, rotate `MOOTOS_SESSION_SECRET` and redeploy.
- If OpenAI requests fail, verify `OPENAI_API_KEY` and API billing in Railway variables.
- If data disappears, verify the volume is attached at `/data` before writing new production data.
- Do not wipe or detach the volume without a backup.
