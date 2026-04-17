# Self-Hosting the Pitwall IQ Backend

This guide is for advanced users who want to run their own backend instead of using the shared Pitwall IQ service. Self-hosting gives you:

- Unlimited AI debriefs (using your own Azure OpenAI deployment)
- A private community leaderboard for your friend group
- Full control over your data

Everyone else — just run `F1_lap_tracker.py` and everything works out of the box.

-----

## Prerequisites

**Linux / macOS:**

```bash
# Azure CLI
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash   # Ubuntu/Debian
brew install azure-cli                                    # macOS

# Azure Functions Core Tools
npm install -g azure-functions-core-tools@4

# jq (used by deploy.sh to parse output)
sudo apt install jq   # Ubuntu/Debian
brew install jq       # macOS

az login
```

**Windows (PowerShell):**

```powershell
winget install Microsoft.AzureCLI
winget install jqlang.jq
npm install -g azure-functions-core-tools@4
az login
```

> The deploy script (`infra/deploy.sh`) is a bash script. On Windows, run it from **Git Bash** or **WSL**.

-----

## Deploy the backend

```bash
cd infra
chmod +x deploy.sh
./deploy.sh <resource-group-name> <azure-region>
# e.g.: ./deploy.sh pitwall-iq-rg eastus
```

The script will:
1. Create the resource group
2. Deploy Cosmos DB, Function App, and Storage Account via Bicep
3. Publish the Python Azure Function
4. Print the environment variables you need

-----

## Point the tracker at your backend

Set these environment variables before starting the tracker (or add them to a `.env` file in the app folder):

**Linux / macOS:**
```bash
export F1_LEADERBOARD_URL="https://<your-func>.azurewebsites.net"
export AZURE_OPENAI_ENDPOINT="https://<your-resource>.openai.azure.com"
export AZURE_OPENAI_KEY="<your-api-key>"
export AZURE_OPENAI_DEPLOYMENT="gpt-4o"
python3 F1_lap_tracker.py
```

**Windows (PowerShell):**
```powershell
$env:F1_LEADERBOARD_URL      = "https://<your-func>.azurewebsites.net"
$env:AZURE_OPENAI_ENDPOINT   = "https://<your-resource>.openai.azure.com"
$env:AZURE_OPENAI_KEY        = "<your-api-key>"
$env:AZURE_OPENAI_DEPLOYMENT = "gpt-4o"
python F1_lap_tracker.py
```

-----

## Sharing with friends

Only one person needs to deploy. Everyone else sets the same `F1_LEADERBOARD_URL` value — no Azure account required for participants.

-----

## Estimated Azure cost

| Resource | Estimated monthly cost |
|---|---|
| Cosmos DB (serverless) | ~$0–$1 for light use |
| App Service Plan (B1 Basic) | ~$13/month |
| Storage Account | < $0.10 |
| **Total** | **~$13–$14/month** |

> The Bicep uses a **Basic B1** dedicated plan rather than the consumption (Y1/Dynamic) tier. Many personal/trial Azure subscriptions have a Dynamic VM quota of 0, which blocks the consumption plan. B1 avoids that restriction entirely.
