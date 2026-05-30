# How to Run on Railway

This guide will walk you through deploying Podly on Railway using the one-click template.

> **Podly is provider-agnostic.** This guide uses [Groq](https://groq.com/) for
> transcription because it has a generous free tier and is the simplest way to
> get going on Railway. You are not locked in: transcription can point at any
> OpenAI-compatible Whisper/Parakeet server, and ad detection works with most
> LLMs (OpenAI, Anthropic, Gemini, Groq, or a local model). See the
> [Transcription](../README.md#transcription-whisper) and `.env.local.example`
> notes for other providers — set the relevant `WHISPER_*` / `LLM_*` variables
> in Railway instead of `GROQ_API_KEY`.

## 0. Important! Set Budgets

Set spending limits before you process anything. Set a $10 budget on Railway
(the minimum; expect a smaller bill). If you use Groq (below), set a $5 budget in
the Groq console too. If you use a different transcription or LLM provider, set
the equivalent limit in that provider's dashboard.

## 1. Get a Transcription API Key (Groq recommended)

The quickest option is Groq — it transcribes quickly and has a free tier:

1.  Go to [https://console.groq.com/keys](https://console.groq.com/keys).
2.  Sign up for a free account.
3.  Create a new API key.
4.  Copy the key and paste it into the `GROQ_API_KEY` field during the Railway deployment.

Prefer something else? Skip the Groq key and instead set `WHISPER_TYPE=remote`
with `WHISPER_REMOTE_BASE_URL` (and `WHISPER_REMOTE_API_KEY` if required) in
Railway, pointing at any OpenAI-compatible transcription server such as
[WhisperX API server](https://github.com/Nyralei/whisperx-api-server) or
[ParakeetX](https://github.com/MaroonBrian1928/parakeetX).

## 2. Deploy Railway Template

Click the button below to deploy Podly to Railway. This is a sponsored link that supports the project!

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/podly?referralCode=NMdeg5&utm_medium=integration&utm_source=template&utm_campaign=generic)

If you want to be a beta-tester, you can deploy the preview branch instead:

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/podly-preview?referralCode=NMdeg5&utm_medium=integration&utm_source=template&utm_campaign=generic)

## 3. Configure Networking

After the deployment is complete, you need to expose the service to the internet.

1.  Click on the new deployment in your Railway dashboard.
2.  Go to the **Settings** tab.
3.  Under **Networking**, find the **Public Networking** section and click **Generate Domain**.
4.  You can now access Podly at the generated URL.
5.  (Optional) To change the domain name, click **Edit** and enter a new name.

![Setting up Railway Networking](images/setting_up_railway_networking.png)

## 4. Set Budgets & Expected Pricing

Set a $10 budget on Railway, plus a budget on whichever transcription/LLM
provider you chose (e.g. $5 on Groq, or use Groq's free tier, which will slow
processing).

Podly is designed to run efficiently on Railway's hobby plan.

If you process a large volume of podcasts, you can check the **Config** page in your Podly deployment for estimated monthly costs based on your usage.

## 5. Secure Your Deployment

Podly uses secure session cookies for the web dashboard and per-feed access tokens (embedded in the feed URL) for RSS feeds and audio downloads. Before inviting listeners, secure the app:

1. In the Railway dashboard, open your Podly service and head to **Variables**.
2. Add `REQUIRE_AUTH` with value `true`.
3. Add a strong `PODLY_ADMIN_PASSWORD` (minimum 12 characters including uppercase, lowercase, digit, and symbol). Optionally set `PODLY_ADMIN_USERNAME`.
4. Provide a long, random `PODLY_SECRET_KEY` so session cookies survive restarts. (If you omit it, Podly will generate a new key each deploy and sign everyone out.)
5. Redeploy the service. On first boot Podly seeds the admin user and requires those credentials on every request.

> **Important:** Enabling auth on an existing deployment requires a fresh data volume. Create a new Railway deployment or wipe the existing storage so the initial admin can be seeded.

After signing in, use the Config page to change your password, add additional users, and copy RSS links via the "Copy protected feed" button. Podly issues feed-specific access tokens and embeds them in each URL so listeners can subscribe without knowing your main password. When you rotate passwords, update the corresponding Railway variables so restarts succeed.

## 6. Using Podly

1.  Open your new Podly URL in a browser.
2.  Navigate to the **Feeds** page.
3.  Add the RSS feed URL of a podcast you want to process.
4.  Go to your favorite podcast client and subscribe to the new feed URL provided by Podly (e.g., `https://your-podly-app.up.railway.app/feed/1`).
5.  Download and enjoy ad-free episodes!

> **Subscribing with auth enabled:** if you turned on authentication (step 5),
> use the **"Copy protected feed"** button on the Feeds/Config page rather than
> the bare `/feed/1` URL. It embeds a per-feed access token so podcast apps can
> fetch the feed without your login. This matters for apps like **Pocket Casts**,
> which fetch feeds from their own servers and therefore need a publicly
> reachable URL — your Railway domain is public, and the token keeps it
> protected.
