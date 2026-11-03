# SlashDr client review deployment

The application already runs locally. This package adds `render.yaml` to deploy the same Python application, frontend and Swagger documentation together on Render. No rewrite to Streamlit or JavaScript is needed.

## Deployment status

These are prepared deployment files. A live client URL exists only after a deployment completes successfully in your Render account. `localhost` links cannot be shared with a remote client.

## Deploy from a private GitHub repository

1. Extract `slashdr-cloud-source.zip` and open its `slashdr-assistant` folder. Create a private GitHub repository, then upload the contents of that folder so `api.py`, `requirements.txt` and `render.yaml` are at the repository root. This archive contains no `.env` or `.venv`.
2. Sign in at <https://dashboard.render.com/> and grant Render access to that repository.
3. Choose **New → Blueprint**, select the repository, and use its root `render.yaml`.
4. Inspect the service configuration. The blueprint requests the `free` compute plan; confirm the plan is available for your account before creating the service. Model API usage is billed separately.
5. When prompted for environment values, supply:

   | Variable | Value |
   | --- | --- |
   | `OPENAI_API_KEY` | Your actual OpenAI API key, entered only in Render's environment settings |
   | `OPENAI_MODEL` | `gpt-4.1-mini` (already supplied by the blueprint) |
   | `REVIEW_USERNAME` | `client-review` (already supplied by the blueprint) |
   | `REVIEW_PASSWORD` | A long unique password you choose for this review |

6. Deploy and wait until the service is live and `/health` returns `{"status":"ok"}`. The service will not start on Render without both reviewer credentials.
7. Open the service's actual HTTPS URL and sign in with the reviewer username/password. Check the app, `/docs`, and a generated answer before sharing the URL.

If using **New → Web Service** instead of a Blueprint, choose Python, build with `pip install -r requirements.txt`, start with `uvicorn api:app --host 0.0.0.0 --port $PORT`, set health check `/health`, and add the same environment values manually.

The files must be at the repository root for this configuration. If placing the project inside an existing repository, set Render's root directory to that subfolder and configure the service accordingly. Do not upload the parent Documents folder or the local virtual environment.

## Check before sending the review link

- The app and `/docs` should show a login prompt without reviewer credentials. `/health` is intentionally public.
- Select P010 and generate a summary. Open its source records and check the answer.
- Select P001 and ask for the last three blood pressure readings.
- Select P004 and ask about allergies; undocumented allergies must not become “no allergies”.
- Try `/.env`; it must not return a secret file.
- Keep only synthetic data in this demonstration. This shared reviewer login is not clinical user/patient authorization.

## Client review note

Replace the placeholders after deployment. Do not send placeholders as working links.

> Please review the SlashDr AI Assistant demonstration at [ACTUAL DEPLOYED HTTPS URL].
>
> API documentation: [ACTUAL DEPLOYED HTTPS URL]/docs
>
> This demonstration uses 100 synthetic patient histories. Please try preparing a patient summary, retrieving BP readings, and opening source records. Feedback on answer usefulness, source accuracy and the workflow is welcome.
>
> Reviewer credentials will be shared separately.

Do not share the OpenAI API key with the client. The review password is separate from that key. Stop or restrict the service after the review if it is no longer needed. Rate limiting is not implemented in this demo; limit the reviewers and configure appropriate API usage controls.

## References

- <https://render.com/docs/deploy-fastapi>
- <https://render.com/docs/blueprint-spec>
