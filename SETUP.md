# Setting up the Measy TikTok bot

You do this once. It takes about an hour, most of it in TikTok's developer portal.
Commands are run in PowerShell from this folder (`C:\Users\tomob\Desktop\measy-tiktok-bot`).

## 1. OpenAI key

1. Copy `.env.example` to `.env` (it is git-ignored) and put your key after `OPENAI_API_KEY=`.
2. Add the same key to GitHub (paste it when asked):

   ```
   gh secret set OPENAI_API_KEY
   ```

Check it works with a free-of-TikTok test that builds three days of slides into `out\`:

```
.\.venv\Scripts\python.exe -m measybot dry-run --days 3
```

(About 15¢: three cover pictures. Add `--no-image` to test the words only, with a placeholder cover.)

## 2. A key that locks the TikTok login

The repo is public, so the TikTok login is stored encrypted. Make a key:

```
.\.venv\Scripts\python.exe -m measybot newkey
```

Put it in `.env` after `TOKEN_KEY=` and add it to GitHub with `gh secret set TOKEN_KEY` (paste the same key).
Keep it: if it's lost, just make a new one and do step 6 again.

## 3. Create the TikTok app

1. Go to <https://developers.tiktok.com/> and log in (any TikTok account works; it can be the Measy one).
2. **Manage apps → Connect an app** (or "Create app"). Name it e.g. *Measy Slideshow Bot*.
3. Fill in the basic info: icon (the Measy logo), category (e.g. Food & Drink / Lifestyle), a one-line
   description ("Sends Measy's daily budget recipe slideshow to our own TikTok drafts, ready for us to add
   a sound and post."), and the links
   **Terms of Service** `https://tomovids.github.io/measy-tiktok-bot/terms.html` and
   **Privacy Policy** `https://tomovids.github.io/measy-tiktok-bot/privacy.html`.
4. **Platforms:** choose **Web** and use the website `https://tomovids.github.io/measy-tiktok-bot/`.
5. **Add products:** **Login Kit** and **Content Posting API**.
   - Login Kit → **Redirect URI**: `https://tomovids.github.io/measy-tiktok-bot/auth.html`
   - Content Posting API: leave *Direct Post* **off** (the bot only makes drafts).
6. **Scopes:** `user.info.basic` and `video.upload`.

## 4. Let TikTok trust the image address

TikTok only downloads slides from an address you've proven is yours.

1. In the app, find **URL properties** (under Content Posting API, "Verify domains / URL prefixes").
2. Add a **URL prefix**: `https://tomovids.github.io/measy-tiktok-bot/`
3. TikTok gives you a small verification file (a `.txt`). Put it in this repo's `site\` folder, then:

   ```
   git add site; git commit -m "TikTok verification file"; git push
   ```

   The *Publish site* workflow puts it online within a minute or two. Check by opening
   `https://tomovids.github.io/measy-tiktok-bot/<the file name>` in a browser.
4. Back in TikTok, press **Verify**.

If TikTok won't accept a github.io address, use a getmeasy.com subdomain instead: add a DNS `CNAME`
record `slides.getmeasy.com → tomovids.github.io`, set `slides.getmeasy.com` as the custom domain in the
repo's **Settings → Pages**, verify the **domain** `getmeasy.com` in TikTok (it gives you a DNS TXT record),
and change `pages_base_url` and `redirect_uri` in `config.toml` (and the Redirect URI in TikTok) to
`https://slides.getmeasy.com/...`.

## 5. Sandbox, test user and keys

1. At the top of the app page switch to **Sandbox** and create a sandbox if asked.
2. **Target users / Add users:** add the Measy TikTok account (accept the invite in TikTok if one arrives).
3. Copy the **Client key** and **Client secret** (from the sandbox, if you're using it) into `.env`, and:

   ```
   gh secret set TIKTOK_CLIENT_KEY
   gh secret set TIKTOK_CLIENT_SECRET
   ```

## 6. Log in once

```
.\.venv\Scripts\python.exe -m measybot authorize
```

A browser opens on TikTok: log in as the **Measy** account and approve. You land on a page showing a code;
copy it into the PowerShell window. Then commit the encrypted login:

```
git add state/tiktok_token.enc; git commit -m "TikTok login"; git push
```

The login lasts about a year; the bot warns in its log a month before it runs out. Repeat this step then.

**Extra accounts (@mealswithmeasy, @ethaniscookingdaily):** add each as a target user in the Sandbox too
(step 5), then, with the browser logged in to TikTok as that account (log out of the others first):

```
.\.venv\Scripts\python.exe -m measybot authorize --account mealswithmeasy
git add state/mealswithmeasy/tiktok_token.enc; git commit -m "TikTok login: mealswithmeasy"; git push
```

Same for `--account ethaniscookingdaily` (its login goes in `state/ethaniscookingdaily/`).
Until an account's login exists the bot just skips that account.

## 7. First real draft

On GitHub: **Actions → Daily TikTok draft → Run workflow**. After a few minutes the TikTok app shows a
notification: open it, add a sound, post. From then on it runs by itself: the workflow checks every 30 minutes and
sends each account's drafts once they're due (times in `config.toml`).

## If something goes wrong

The run turns red on GitHub and GitHub emails you. Open the run and read the last lines of the failed
step: the bot says what happened and what to do. Common ones:

| Message | What to do |
|---|---|
| *at most 5 waiting drafts* | Post or delete the drafts waiting in your TikTok inbox, then run the workflow again. |
| *login has expired* | Step 6 again. |
| *hasn't verified the image address* | Step 4. |
| *Update the TikTok app* | Drafts need TikTok 31.8 or newer on your phone. |

### If TikTok blocks drafts

Tested 2026-10-08: drafts from the sandbox app reach the inbox, so no review was needed. Keep this in case TikTok changes that.


TikTok's docs say apps it hasn't reviewed can only post privately. That is written for direct posting; it
is not clear whether it also covers drafts, so the first real run (step 7) tells us. If it is blocked:

- **Ask TikTok to review the app:** in the developer portal, **Submit for review**. You need the
  privacy policy and terms links, and a short screen recording showing the flow (running `authorize`,
  the draft arriving in TikTok). Reviews take from a few days to a couple of weeks.
- **Or use a posting service** that already has TikTok's approval and supports drafts (e.g. Upload-Post or
  Ayrshare, about $15-30 a month). Only `measybot/tiktok.py` would change.
