# Internship Finder → Slack

Scans ~1,000 company job boards (plus the community-maintained Simplify internship list)
every 2 hours, and posts a **daily roundup at 9 AM Pacific** with up to 5 new roles in each section:

- 🧭 Product Management
- 🧠 Strategy & Consulting
- 📈 Finance, VC & Real Estate
- 📊 Data & Analytics
- 📣 Marketing & Growth
- 🌱 Freshman & Sophomore Programs

```
🧭 Product Management
Associate Product Manager Intern
🏢 Google ⭐ · 📍 Mountain View, CA
☀️ Summer 2027 · 🎓 Grad 2028
```

It's tuned for **undergrad summer internships in the US**. MBA / Master's / PhD roles are
skipped. Business, strategy, product and consulting roles come from **tech companies**,
and the biggest companies (Fortune 100 / big tech, marked ⭐) are picked first. For each
role it reads the full description to show the graduation year and season it asks for.
Roles that don't make the day's top 5 carry over to the next digest (for up to 7 days).

## How it works

- **Company boards.** Most big companies post jobs through Workday, Greenhouse, Lever,
  Ashby, SmartRecruiters or Oracle Cloud, which have public job feeds. The scanner asks
  each one for internship / co-op / summer analyst roles.
- **Simplify feed.** Covers companies with custom careers sites that can't be scanned
  directly (Google, Meta, Apple, Amazon, Microsoft, Tesla, TikTok…).
- **Memory.** `data/seen.json` records what's already been posted, so each job is posted
  once. The same role in several cities becomes one post. A role found both on a
  company's board and in the Simplify feed is posted once.
- **No flood on day one.** The first time a board is scanned, its current openings are
  recorded quietly. After that, only newly released roles are posted.

## Setup (about 10 minutes)

### 1. Create a Slack webhook

1. Go to <https://api.slack.com/apps> → **Create New App** → **From scratch**. Name it
   (e.g. "Internship Bot") and pick your workspace.
2. In the left menu click **Incoming Webhooks** → switch it **On**.
3. Click **Add New Webhook to Workspace**, choose the channel (e.g. `#internships`), **Allow**.
4. Copy the webhook URL (starts with `https://hooks.slack.com/services/...`). Keep it
   private, since anyone with it can post to your channel.

*Want tech and business in separate channels?* Add a second webhook for the other
channel (step 3 again). See step 3 below for how to wire them up.

### 2. Put this code on GitHub

1. Create a free account at <https://github.com> if you don't have one.
2. Click **+ → New repository**. Name it `internship-finder`. Choose **Public** (unlimited
   free runs; nothing in it is private, and the webhook stays secret).
   Private works too, but to stay within the 2,000 free minutes a month, change the
   schedule to every 3 hours (see Customizing) and check usage after the first week.
3. On the new repo page click **uploading an existing file**, and drag in **everything
   inside** the unzipped `internship-finder` folder, including the hidden `.github`
   folder. (On a Mac, press **Cmd + Shift + .** in Finder to show hidden folders.)
   Then click **Commit changes**.
   - Check that the repo now shows a `.github/workflows` folder. If it doesn't, the
     schedule won't run. Upload that folder again.

   Prefer the command line?
   ```bash
   cd internship-finder
   git init && git add . && git commit -m "Internship finder"
   git branch -M main
   git remote add origin https://github.com/<you>/internship-finder.git
   git push -u origin main
   ```

### 3. Add the webhook as a secret

Repo → **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|---|---|
| `SLACK_WEBHOOK_URL` | your webhook URL |
| `SLACK_WEBHOOK_TECH` *(optional)* | webhook for a tech channel |
| `SLACK_WEBHOOK_BUSINESS` *(optional)* | webhook for a business channel |

If you set the optional ones, tech and business roles go to their own channels.
Anything else goes to `SLACK_WEBHOOK_URL`.

### 4. Turn it on

1. Repo → **Actions** tab. If asked, click **I understand my workflows, go ahead and enable them**.
2. *(Recommended, once)* Click **Update company list** → **Run workflow**. This looks up
   the business firms in `data/business_seed.txt` (banks, consulting, consumer goods…)
   and takes ~10–20 minutes. Its summary page lists any company it couldn't find.
3. **Test it:** click **Scan for internships** → **Run workflow** → set *mode* to **test** →
   **Run workflow**. In ~5 minutes a sample digest (2 roles per section, from roles open
   right now) appears in Slack. Test mode saves nothing, so run it as often as you like.
4. **Go live:** run it again with *mode* **normal**. This first real run posts nothing on
   purpose, because it's recording what's already open. From then on it scans every 2 hours
   and posts the digest each morning. Mode **digest-now** posts whatever is queued immediately.

If the save step fails with a permissions error: **Settings → Actions → General →
Workflow permissions → Read and write permissions → Save**.

## Customizing

| Want to… | Do this |
|---|---|
| Change digest time, roles per section, or sections | `digest:` in `config.yaml` |
| Change how often it scans | Edit the `cron` line in `.github/workflows/scan.yml` (`17 */3 * * *` = every 3 hours) |
| Change which titles count | `include_title_patterns` / `exclude_title_patterns` in `config.yaml` |
| Change target grad years | `target_grad_years` in `config.yaml` |
| Include fall / winter / spring / co-ops | `include_off_season: true` in `config.yaml` |
| Change the role mix | `post_categories` and `engineering_companies` in `config.yaml` |
| Allow business roles from non-tech companies | `tech_companies_only_for: []` in `config.yaml` |
| Mark a company as tech, Tier 1 or Tier 2 | `data/company_tiers.yaml` |
| Include non-US roles | `us_only: false` in `config.yaml` |
| Add a specific company | Add `Company Name \| <link to any job on their careers site>` to `data/companies_manual.txt` |
| Add business firms to look up | Add names to `data/business_seed.txt`, then run **Update company list** |
| Remove a company | Add its name to `data/companies_exclude.txt` |

Edit files right on GitHub (click the file → pencil icon → Commit). The next run uses
your changes.

## Checking on it

- **Actions** tab → click any run → the summary shows boards scanned, how many new
  roles were posted, and which boards failed.
- A few boards failing is normal (companies change careers sites). Boards failing 12+
  runs in a row are listed so you can remove or fix them.
- The company list refreshes itself monthly from the Simplify data.

## Limits worth knowing

- **Coverage.** Companies on iCIMS, Taleo, Eightfold or fully custom sites can't be scanned
  directly. Big tech ones are still covered through the Simplify feed. Business firms on
  those systems (e.g. some consulting firms) won't be. The discovery report lists them.
- **Timing.** "Every 2 hours" is GitHub's best effort. Busy times can delay a run.
- **Inactivity.** GitHub pauses schedules in repos with no activity for 60 days. The bot's
  own commits normally keep it active. If it ever pauses, the Actions tab has a button to
  turn it back on.
- **Slack free plan** shows the last 90 days of messages, which is fine for job alerts.

## Running locally (optional)

```bash
pip install -r requirements.txt
python scan.py --dry-run --limit 100   # prints matches, posts nothing, saves nothing
python tests/test_e2e.py               # offline test with mocked job boards
```
