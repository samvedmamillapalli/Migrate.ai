

Database migrator

- guesses what will happen when u change ur database (how long it takes, how much space it uses, if its safe to undo), then actually tests it on a fake copy first and checks if the guess was right
- it remembers every past guess and what really happened, so next time it sees something similar it gives a better guess instead of guessing blind again
- other tools just say "this might be risky" but dont actually test it or get smarter over time, thats the missing piece
- uses cockroachdb to store the memory and spin up the fake test copy, and aws to do the thinking and run the test safely

The user data integration idea isnt that useful because the metric we need to measure for this idea isnt the number of databases, but the number of data migrations. We should train the model on the number of migrations that are taking place and store that data into cockroach to make the app work better and showcase better for the hackathon. 

I was thinking we could find histories or open source migration histories from different databases to match up our model against it to train. Theres a lot of databases and migrations done on railway apps, github, django, all that shit so we could find schemas from that and migration histories and context and provide that to the model. We might have to figure out formatting and storage and processing for that and it would be its own algorithm but we can most likely find one online or make our own pretty easily would just be timetaking once but could be used repetitively. 

Ok and when this first idea happens we might have some gaps in the data still so what we could do is make our own datasets and migrate between datasets we just make using AI or whatever, but specifically the aspects of migrations that were missed by the open source data, because I dont know if we can fully train our model based on that data. We’d essentially just have to find a big quantity of migrations and the most unique migrations that exist.

  


Migration Oracle Plan (samrita version)

1. the actual special part of this project is predict then verify then grade then remember. just testing on a copy = other tools already do that. just giving a risk label = other tools already do that too. the loop is the new thing  
  

2. shadow cluster(group of dbs) work (samved) — script to create a cluster, seed it, run migration, measure it, delete it. use ccloud cli, free tier. this is the riskiest part and needs to work first cuz everything else depends on it. need to check how slow free tier provisioning is and how many clusters we can make per day (I genuinely need to understand this)  
  

3. structure reader (samved + samrita for ui) — read only connection to db that grabs table names, column types, row counts, sizes. nothing more than that. gotta make sure the connection is actually forced read only, not just labeled that way  
  

4. the loop itself (samved) — bedrock takes the migration + db structure + similar past migrations, writes a prediction (time, storage, rollback risk, confidence, explanation). then it actually runs on shadow cluster (verify), then compares guess vs real result (grade), then saves it with an embedding (remember). need to figure out early what counts as "close enough" for grading  
  

5. memory / vector layer (samved, samrita helps review) — table storing every migration result, embeddings made from the sql + the reasoning + surprises (not just the sql alone), vector search to pull up similar past ones. log every retrieval so we can show it off later  
  

6. aws orchestration (samved) — step functions to run the whole pipeline and guarantee cleanup even if it fails, lambdas for each step, s3 for storing run data, cloudwatch for tracking stuff. every aws tool used needs a real reason or we cut it  
  

7. mcp (samved) — used to watch the shadow cluster live during testing (like watching backfill progress). this is a nice to have, not the main thing. main things are ccloud cli and vector search  
  

8. seeded corpus(big group of pieces of information samritaaaa) — grab real migrations from open source project histories + make up our own on fake tables of diff sizes, run all of it thru the real loop before demo day so the "accuracy getting better" graph is real not fake. no plan to get real users, this replaces that  
  

9. dashboard (samrita) — shows prediction vs what actually happened, error per migration, the accuracy curve over time, and a panel showing which past migrations got pulled up for a prediction(matters most for winning the memory category)  
  

10. connect + input screen (samrita) — paste connection string (read only), paste the migration, see results  
  

11. auth (samrita, quick, 1-2 days) — just clerk login, each user only sees their own stuff, billing as future plan on a slide  
  

12. security (samved, ongoing) — read only enforced, least access for lambdas, api keys stored safe in secrets manager, no secrets pushed to the public repo  
  

13. observability (samved) — cloudwatch dashboards for timing, teardown success, error tracking, logs with a run id so we can trace everything  
  

14. demo stuff (samrita leads, both help) — video under 3 min, public repo w maybe MIT license, working demo link, explanation of tools used  
  


Week by week (rough, simple)

week 1: get the shadow cluster loop working manually, need it to work 3x in a row before doing anything else. also start repo, db schema, auth, start grabbing open source migrations

week 2: wrap loop in step functions w guaranteed cleanup, build structure reader, figure out the grading rules on paper, start building connect/input screen

week 3: hook up the full loop w bedrock, memory retrieval feeding predictions, mcp watching live test, start dashboard. by end of week one full migration should go thru automatically and show up graded

week 4: run a bunch of migrations thru the corpus so accuracy curve is real, write video script now not later, tune the memory retrieval so we have a good example to show off

week 5: security check, test what happens if a run fails mid way (should still clean up, good demo moment), polish dashboard, full practice runs of the demo

week 6: freeze features monday, record video (multiple takes), finish readme, license, double check demo link works from a fresh browser, submit early w buffer days before deadline

Built now vs just planned on paper

built for real: everything above, single region, free tier clusters, basic user auth

just a slide/paragraph, not built: billing, multi region stuff, handling super huge databases (be honest that free tier cant test a 10tb table for real), shared team memory, github integration, deeper compliance stuff

Top risks

1. free cluster spin up might be too slow or limited — check this in week 1 before promising anything, if its bad have backup plan (keep a small pool of pre made clusters ready to reuse)
2. cleanup might fail and leave clusters running (wastes money) — make sure teardown always happens even on failure, plus a backup job that deletes anything left over after 30 min
3. small shadow clusters might not represent real big tables accurately — be upfront about this, measure per size tier instead of pretending its exact
4. memory retrieval might be weak if corpus is small — build the corpus on purpose to include similar migrations worded differently, so it actually has good examples to pull up
5. ai prediction output might come out messy/broken formatting — strict format checking w one auto retry if it breaks

Demo video plan (under 3 min)

1. explain the gap fast, current tools just guess or give generic warnings, nothing tests + grades + remembers
2. paste a migration, show it reading db structure, say clearly its read only and never touches real db
3. show the prediction + memory panel showing which old migrations it pulled from, especially one that looks totally different but is actually the same type of issue
4. live shadow test running for real on camera, cluster gets made, tested, deleted
5. show prediction vs actual result side by side, graded, saved to memory
6. show the accuracy curve going up over time, be honest that the history was built by running real migrations during dev
7. quick shoutout of each tool used and why

end goal: after watching, someone should understand "it grades itself and gets smarter" not just "it tests on a copy." if they only get the second one the video failed

  
Migration Oracle: System Design (samrita version)

1. big picture — app is split into two parts. a light "control plane" (railway, fastapi) that just starts things and reads status, and a "heavy" execution part (aws) that actually does the work. control plane never touches the shadow cluster or bedrock directly. this matters cuz even if railway crashes mid run, the run keeps going since all the real state lives in step functions + cockroachdb, not on railway. mcp is used for accessing the database many instances.   
  

2. pieces of the system  
  


- web app (vercel, next.js) — just the ui, talks to fastapi, checks run status every 2 sec while something is running
- control plane api (railway, fastapi) — checks login (clerk), handles connections/runs, reads db structure, starts the step function, feeds data to dashboard. doesnt hold state itself, just kicks things off. only has permission to start 1 specific workflow and write 1 secret, nothing more
- structure reader (inside fastapi) — grabs table names, column types, row counts, sizes from the db. if it tries the connection and it CAN write (not read only), it rejects it, thats how we prove its actually read only not just labeled that way
- step functions (the orchestrator) — runs the whole predict → provision → verify → grade → remember process. picked "standard" not "express" cuz runs take minutes and we want to see the history in console for the demo video
- lambda functions, one job each — predict_fn (makes the prediction), provision_fn/teardown_fn (spins up/deletes shadow cluster), seed_fn (loads fake data into shadow), verify_fn (runs the migration + watches it thru mcp), grade_fn (scores prediction vs reality), remember_fn (saves it with an embedding), sweeper_fn (runs every 10 min, deletes any leftover clusters older than 30 min just in case something got missed)
- memory layer (cockroachdb) — one cluster w two databases inside, one for app stuff (users/runs) one for memory stuff (verdicts/embeddings). vector search lives right in the same db
- secrets (aws secrets manager) — this is where user db passwords actually live, cockroachdb just stores a pointer to it, never the real password
- observability (cloudwatch) — tracks timing, errors, and most importantly the accuracy curve over time

1. how one migration flows thru the system, step by step

- user pastes migration → fastapi checks login, refreshes db structure read (only time real db gets touched), saves a run row, kicks off the workflow
- predict_fn looks up similar past migrations, sends everything to bedrock, gets back a prediction, saves it (frontend can already show this part before verification even finishes, which is a good demo moment)
- provision_fn makes a temp shadow cluster
- seed_fn fills it with fake data matching the real db's scale
- verify_fn actually runs the migration on the shadow, watches it live thru mcp
- teardown_fn deletes the shadow cluster right after
- grade_fn compares the guess to what really happened, scores it, writes a note if it was way off
- remember_fn turns all that into an embedding and saves it so future migrations can find it
- dashboard updates to show prediction vs actual + the memory that got pulled up + the updated accuracy graph

1. database tables (just what each one is for, simply)

- users — just clerk user ids
- db_connections — stores a pointer to the secret, not the actual password
- migration_runs — one row per migration attempt, tracks its status thru the whole pipeline
- shadow_clusters — tracks each temp cluster's state so the sweeper knows what to check
- predictions — the ai's guess
- verifications — what actually happened
- migration_verdicts — the graded result + the embedding, this is literally the memory
- retrieval_log — records which old migrations got pulled up for a new prediction, this feeds the memory panel in the dashboard

the retrieval query itself is basically the core of the whole product: search past graded migrations by embedding similarity, return the top 5 most similar ones, both the user's own history and the shared seeded corpus

1. the shadow cluster process, step order

predict → provision → wait till ready → seed data → measure baseline → run the actual migration → watch it finish → measure again → destroy cluster → grade → remember → done

cleanup happens no matter what goes wrong at any step, since every step has a fallback that routes straight to teardown. plus the sweeper job double checks every 10 min for anything that slipped thru. if a migration just takes too long (over 900 sec) it still gets graded, just marked as "took too long" instead of thrown away, since knowing that itself is useful info

1. security stuff

- user's db password only lives in secrets manager, encrypted, cockroachdb just holds a pointer to it
- password is only ever in memory for one request, never logged
- every user can only see their own stuff, checked server side off their login token, never trusted from the request itself
- each lambda only has the exact permission it needs and nothing more (predict_fn can access bedrock and the memory db, provision/teardown/sweeper can access the cluster api key, seed_fn can access the s3 bucket, thats it)
- the shadow cluster gets its own random temp password that dies with the cluster
- mcp access to the shadow cluster is read only, actual migration commands go a separate direct path

1. what happens when stuff breaks (just the big ones)

- cant reach user's db → tells user right away, nothing was created yet so nothing to clean up
- db credential turns out to have write access → rejected immediately, nothing gets stored
- shadow cluster fails to spin up → retries automatically, then fails clean, sweeper double checks after
- migration takes too long on the shadow → still gets graded as a "timeout" finding instead of wasted, cluster still gets deleted
- ai gives back broken/invalid prediction → auto retries once, then fails clean if still broken
- cleanup itself fails → alert goes off immediately, sweeper deletes it within 10 min anyway
- saving to memory fails after grading → run still shows as done, gets fixed later automatically
- railway itself crashes mid run → doesnt matter, nothing important was stored there, run keeps going in aws the whole time, this is honestly the best "this is solid engineering" point to bring up to judges

1. what happens as it grows (mentioned briefly, not built)

- free tier cluster limits are the actual bottleneck, for the hackathon just cap it at 2 runs at once and queue the rest
- for a real product later: keep a pool of pre made clusters ready to go instead of making new ones each time, way faster
- bedrock might rate limit under heavy use, retry logic handles that for now
- railway is a single instance for the demo, in a real product it'd run on multiple instances
- cockroachdb itself basically wont be the bottleneck even at bigger scale, which is worth mentioning as a selling point

  
Temporal — github.com/temporalio/temporal, MIT license, already plain sql so basically zero work, includes a real incident case (bad index add that broke prod). our main source.

Apache Superset — github.com/apache/superset, Apache 2.0, migrations are in python (alembic) but super easy to convert to sql since the commands are basically 1:1. good backup source for volume.

Apache Airflow — same deal as superset, alembic/python, apache 2.0, easy to convert, good for rollback examples since it has clean up/down pairs.

Zulip / NetBox — apache 2.0, but django migrations which are messier to convert, only use if we need more variety later.

  


Temporal

- Repo: [++https://github.com/temporalio/temporal](https://github.com/temporalio/temporal)++
- Migrations folder: [++https://github.com/temporalio/temporal/tree/main/schema/postgresql/v12](https://github.com/temporalio/temporal/tree/main/schema/postgresql/v12)++
- License: [++https://github.com/temporalio/temporal/blob/main/LICENSE](https://github.com/temporalio/temporal/blob/main/LICENSE)++

Apache Superset

- Repo: [++https://github.com/apache/superset](https://github.com/apache/superset)++
- Migrations folder: [++https://github.com/apache/superset/tree/master/superset/migrations/versions](https://github.com/apache/superset/tree/master/superset/migrations/versions)++
- License: [++https://github.com/apache/superset/blob/master/LICENSE.txt](https://github.com/apache/superset/blob/master/LICENSE.txt)++

Apache Airflow

- Repo: [++https://github.com/apache/airflow](https://github.com/apache/airflow)++
- Migrations folder: [++https://github.com/apache/airflow/tree/main/airflow-core/src/airflow/migrations/versions](https://github.com/apache/airflow/tree/main/airflow-core/src/airflow/migrations/versions)++
- License: (standard Apache 2.0, ASF project, same license structure as Superset)

Zulip

- Repo: [++https://github.com/zulip/zulip](https://github.com/zulip/zulip)++
- Migrations folder: [++https://github.com/zulip/zulip/tree/main/zerver/migrations](https://github.com/zulip/zulip/tree/main/zerver/migrations)++
- License: [++https://github.com/zulip/zulip/blob/main/LICENSE](https://github.com/zulip/zulip/blob/main/LICENSE)++

NetBox

- Repo: [++https://github.com/netbox-community/netbox](https://github.com/netbox-community/netbox)++
- Migrations: spread across per-app folders like [++https://github.com/netbox-community/netbox/tree/develop/netbox/dcim/migrations](https://github.com/netbox-community/netbox/tree/develop/netbox/dcim/migrations)++
- License: (Apache 2.0, per earlier research)

  
This is just my reserach. Do what you feel is better. 

This project is for this hackathon. 

# **CockroachDB × AWS Hackathon - Build with Agentic Memory**

### Agents that think. Agents that act. Agents that remember; reliably, globally, at any scale.

##### **🪳 CockroachDB × AWS Hackathon:**

CockroachDB and AWS invite developers, engineers, and AI builders to create the next generation of agentic applications. Harness CockroachDB's distributed AI capabilities, fully managed MCP Server, agent-ready ccloud CLI, open-source Agent Skills Repo, LangChain integrations and Claude/Cursor plugins - all on AWS - to build AI agents with production-grade, persistent memory.

##### **Why Agentic Memory? Why Now?**

AI agents are rapidly moving from experiments into real production workflows, like writing code, running pipelines, diagnosing incidents, and driving more application traffic than any human could. But here's the problem: agents need memory that never goes down.

An agent whose memory goes offline doesn't degrade gracefully, it stops. Traditional databases were optimized for human-scale reads and writes. Agentic systems are different: they spawn autonomously, write constantly, and require memory that persists across regions, failures, and scale  (with zero data loss and no maintenance windows).

CockroachDB was built for exactly this. It is the system of record for agentic memory: globally distributed, always-on, PostgreSQL-compatible, and now natively integrated into the agent toolchain through MCP, cloud, and an open-source skills ecosystem.

This hackathon is your invitation to build on that foundation.

#### **The Challenge**

**Build an agentic application that uses CockroachDB as its persistent memory layer, deployed on AWS.**

Your agent should store, retrieve, and act on memory whether that's conversation history, user context, task state, embeddings, or structured transactional data. The best submissions will demonstrate that memory is not an afterthought, it is the thing that makes an agent useful in production.

All submissions must use at least two of the following CockroachDB tools:

- **CockroachDB Cloud Managed MCP Server** — Connect AI agents directly to CockroachDB clusters with a single config snippet from the Cloud Console. Works natively with Claude Code, Cursor, and VS Code. Safe by default: read-only mode, full audit logging, zero custom proxy required. Endpoint: [https://cockroachlabs.cloud/mcp](https://cockroachlabs.cloud/mcp)
- **CockroachDB Distributed Vector Indexing** — Store and query embeddings at scale using CockroachDB's vector support with distributed indexing. Semantic search and retrieval stay fast as your data grows — no separate vector store to maintain, no reindexing pain, and no consistency gaps between your vector data and your operational database. Ideal for RAG pipelines, long-term agent memory, and semantic search applications.
- **ccloud CLI (Agent-Ready)** — Give your agent direct, secure access to the full CockroachDB Cloud control plane. Provision clusters, manage backups, configure networking, monitor audit logs — all from the terminal. Designed for AI with consistent noun-verb patterns, JSON output on every command, and granular service-account-based RBAC.
- **CockroachDB Agent Skills Repo (Open Source)** — A curated, open-source collection of machine-executable Agent Skills encoding CockroachDB expertise. Skills span onboarding, query/schema design, operations, performance, security, and observability. Portable across Claude, Cursor, LangChain, and any MCP-compatible client.

All submissions must also use at least one AWS service:

- Amazon Bedrock (foundation models, knowledge bases, or agents)
- AWS Lambda (serverless agent execution)
- Amazon ECS / EKS (containerized agent workloads)
- Amazon S3 (artifact or document storage)
- Amazon SageMaker (model training or inference)
- Amazon Bedrock Agents (multi-step agentic workflows)
- Any other AWS service that powers your agent's environment**Judging Criteria**
  - **Agentic Memory Design**  
  Does CockroachDB play a meaningful, production-grade role as the agent's memory layer? Is it used for more than toy queries — state, embeddings, context, or transactional data at real scale?
  - **Technical Implementation**  
  Is the integration with CockroachDB tools (distributed vector index, MCP Server, ccloud CLI) quality software engineering? Does the agent use the tools correctly and safely?
  - **Real-World Impact**  
  How big of an impact could the project have on real users or workflows? Is the use case meaningful, not just technically impressive?
  - **Production Readiness**  
  Is the design secure, observable, and scalable? Has the team thought about resilience, access control, and what happens when things go wrong?
  - **Creativity & Originality**  
  Is this a genuinely new idea or a novel application of the technology? Does it demonstrate insight into what makes agentic systems different from traditional apps?

  


