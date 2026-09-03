# Streamlit Community Cloud deployment

LogCouncil is prepared for deployment from the public GitHub repository without secrets or an external API key.

## Privacy boundary

A Community Cloud deployment is remote processing: uploaded logs are sent to the Streamlit-hosted app environment. LogCouncil does not forward them to an external LLM or API, but users must not upload production logs unless they are authorized to send that data to the hosting environment. Run the app locally when logs must remain on the user's machine.

## Community Cloud fields

- Repository: `chienshaochun/log-council`
- Branch: `main`
- Entrypoint: `app.py`
- Python: `3.12`
- Secrets: leave empty

From <https://share.streamlit.io>, select **Create app**, choose **Yup, I have an app**, enter the values above, open **Advanced settings** to confirm Python 3.12, and deploy.

## Dependency contract

Community Cloud reads the root `requirements.txt`, which installs LogCouncil with its pinned UI extra. The local Conda environment is intentionally named `environment.local.yml` so Cloud does not select it as a competing dependency file.

The root `.streamlit/config.toml` keeps the platform upload limit aligned with LogCouncil's 50 MB application-level validation. No `packages.txt` is required because the app has no external Debian package dependency.

## Automated deployment gate

GitHub Actions repeats the same gate used by the previous Streamlit projects on Ubuntu and Python 3.12:

1. install the root `requirements.txt` plus pytest;
2. run the complete test suite;
3. execute `python scripts/validate_deployment.py` against the committed root `app.py`;
4. require the full pasted-log analysis flow, all five result tabs, four summary metrics, and the safe JSON download to render without a Streamlit exception or error.

Do not deploy a commit until the `CI / test-and-deployment-smoke` check is green.

## Post-deploy check

1. Open the assigned `streamlit.app` URL.
2. Paste a small UTF-8 log sample and select **開始分析**.
3. Confirm that all five result tabs render.
4. Download the JSON report and verify that it contains `run_id`, `agent_messages`, `correlations`, and `parse`.
5. Never add `.streamlit/secrets.toml` to Git; it is ignored defensively even though this version needs no secrets.
