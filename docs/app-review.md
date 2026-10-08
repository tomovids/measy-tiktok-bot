# TikTok app review (only if drafts are blocked for the sandbox app)

## "Explain how each product and scope works" (923 / 1000 characters)

```
Measy Slideshow is an internal tool for Measy, a UK meal-planning app. It sends our own daily recipe slideshow to our own TikTok account as a draft. It is not offered to other users.

Login Kit + user.info.basic: the Measy account owner logs in once through our website (redirect page tomovids.github.io/measy-tiktok-bot/auth.html) to authorise the tool, and the tool shows the connected account's display name to confirm it is the right account. We store only the encrypted access and refresh tokens and the open ID.

Content Posting API + video.upload: every morning our scheduled job builds a 7-photo slideshow (cover, five recipe cards, Measy promo) and calls the photo post endpoint with post_mode MEDIA_UPLOAD and PULL_FROM_URL from our verified URL prefix. The draft arrives in the creator's TikTok inbox, where a person adds a sound and posts it in the TikTok app. We never post directly and do not use Direct Post.
```

## Demo video (record with the sandbox app, screen + phone)

1. Show the website `https://tomovids.github.io/measy-tiktok-bot/` (must match the app's website URL).
2. Run `python -m measybot authorize`: the TikTok consent screen (Login Kit, both scopes), the code page,
   "Connected as: <Measy account>".
3. On GitHub: Actions → Daily TikTok draft → Run workflow; show the log reaching `SEND_TO_USER_INBOX`.
4. On the phone: the TikTok inbox notification, the draft opening with the 7 photos and caption,
   adding a sound, posting.
