# Host systemd units

Copy to `/etc/systemd/system/` on the prod box (they are not deployed by CI).
Every `ExecStart` must pass `--env-file .env --env-file .env.deploy`; without
`.env.deploy`, `IMAGE_TAG` falls back to the stale `:local` image.

`geo-ai-extract.service` has no timer: the `ai-extract.conf` drop-ins start it
after each successful scrape, because a scrape can take over an hour.

```sh
sudo cp -r deploy/systemd/*.service deploy/systemd/*.timer deploy/systemd/*.service.d /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now geo-scrape.timer geo-scrape-full.timer
```
