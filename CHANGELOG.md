# Changelog

## [0.2.2](https://github.com/gabrielkpo/lifter/compare/v0.2.1...v0.2.2) (2026-10-19)


### Bug Fixes

* **agents:** a coach turn ends before the hosted function's 60 s ([#92](https://github.com/gabrielkpo/lifter/issues/92)) ([c3e723d](https://github.com/gabrielkpo/lifter/commit/c3e723d4b15eb86f4b552eb637e4ef5e8c6ca930))
* **agents:** planner round 3, a missed set and fewer reps never raise the load ([#91](https://github.com/gabrielkpo/lifter/issues/91)) ([38a7d34](https://github.com/gabrielkpo/lifter/commit/38a7d34286ea6c77ac92c7c3e6b6a1193849fa85))
* **agents:** the coach sees each part's lines and never leaves a new part empty ([#93](https://github.com/gabrielkpo/lifter/issues/93)) ([b3983e4](https://github.com/gabrielkpo/lifter/commit/b3983e43eaf8faf8b15dcedde90e880e1eff93bb))
* the coach's changes can be undone, one part per kind in a session, a clearer coach screen on a phone ([#95](https://github.com/gabrielkpo/lifter/issues/95)) ([116661d](https://github.com/gabrielkpo/lifter/commit/116661d7c2154d867c6ac5e93ede99935916cd99))

## [0.2.1](https://github.com/gabrielkpo/lifter/compare/v0.2.0...v0.2.1) (2026-10-19)


### Bug Fixes

* **web:** the coach's thread never hides under the bars, and every planned part is shown ([#89](https://github.com/gabrielkpo/lifter/issues/89)) ([fccfce2](https://github.com/gabrielkpo/lifter/commit/fccfce26381fe600f866763541cc001680225d34))

## [0.2.0](https://github.com/gabrielkpo/lifter/compare/v0.1.3...v0.2.0) (2026-10-19)


### Features

* the coach in the app, a conversation where saying it is deciding it ([#86](https://github.com/gabrielkpo/lifter/issues/86)) ([c3a3dc8](https://github.com/gabrielkpo/lifter/commit/c3a3dc84459bb016f95c7b7f0c39316266ddd81e))


### Bug Fixes

* **ops:** a sync missed in a dark wake is caught up at the next use of the Mac ([#87](https://github.com/gabrielkpo/lifter/issues/87)) ([7536708](https://github.com/gabrielkpo/lifter/commit/75367087cbf5a4d95be551e9a00cdb62b1742980))

## [0.1.3](https://github.com/gabrielkpo/lifter/compare/v0.1.2...v0.1.3) (2026-10-18)


### Bug Fixes

* **agents:** the coach's tool calls run one at a time, in the model's order ([#83](https://github.com/gabrielkpo/lifter/issues/83)) ([c5007e8](https://github.com/gabrielkpo/lifter/commit/c5007e80d093aecb1ec9ea4ff0506a6c38dbd635))
* the agents lose their table-wide insert on proposals, the Mac stays awake through its jobs ([#85](https://github.com/gabrielkpo/lifter/issues/85)) ([b06cd90](https://github.com/gabrielkpo/lifter/commit/b06cd90cd5292f0ae1003a63b8a802c552840dcb))

## [0.1.2](https://github.com/gabrielkpo/lifter/compare/v0.1.1...v0.1.2) (2026-10-18)


### Bug Fixes

* **agents:** the coach sees the forbidden exercises and fixes an invalid payload at once ([#78](https://github.com/gabrielkpo/lifter/issues/78)) ([1fb54c2](https://github.com/gabrielkpo/lifter/commit/1fb54c2b6d51c776e761ff8391e20d5b25203291))
* suggestions accepted only as presented, every programme change under the guardrail, versioned logs ([#81](https://github.com/gabrielkpo/lifter/issues/81)) ([876ab1c](https://github.com/gabrielkpo/lifter/commit/876ab1c6d8a441a4658a51091e5b7463e250f547))
* the agents' audit, the conversation and the change log are read only by the roles that need them ([#76](https://github.com/gabrielkpo/lifter/issues/76)) ([7c29179](https://github.com/gabrielkpo/lifter/commit/7c2917946936a3892eb416d7a260aeed1506bc3f))
* the closing audit's low findings on the app, the API, the Mac and the trace ([#82](https://github.com/gabrielkpo/lifter/issues/82)) ([07a8749](https://github.com/gabrielkpo/lifter/commit/07a874912b8140842548dff9b5b74be64e268bf3))


### Documentation

* **bench:** the planner's two review touch-ups, measured on 3 runs ([#77](https://github.com/gabrielkpo/lifter/issues/77)) ([56bcdf8](https://github.com/gabrielkpo/lifter/commit/56bcdf800542c738031ed949fccd6588e1a08ed4))

## [0.1.1](https://github.com/gabrielkpo/lifter/compare/v0.1.0...v0.1.1) (2026-10-16)


### Bug Fixes

* **agents:** the coach finds the right session, its tables and its last change ([#73](https://github.com/gabrielkpo/lifter/issues/73)) ([27065d1](https://github.com/gabrielkpo/lifter/commit/27065d1d690e48ad8412e76d7c0cc9e2ba3078ae))

## 0.1.0 (2026-10-16)


### Features

* **agents:** the coach in conversation, its tools and its bench scenarios ([#64](https://github.com/gabrielkpo/lifter/issues/64)) ([f6fbfe4](https://github.com/gabrielkpo/lifter/commit/f6fbfe4841c830fa1db0b2744c127469ec028af4))
* **api:** host the API on Vercel behind a token, the app reads Neon through its server ([#25](https://github.com/gabrielkpo/lifter/issues/25)) ([c083ec0](https://github.com/gabrielkpo/lifter/commit/c083ec01a0f8612fb209b7cdefd414575dc6e8ed))
* **api:** read-only HTTP API for the app (slice 1) ([#13](https://github.com/gabrielkpo/lifter/issues/13)) ([106673d](https://github.com/gabrielkpo/lifter/commit/106673d3ea337ee60439b4fe2f490034ed944b9e))
* **app:** athlete profile and declared health issues, no accent bar ([#36](https://github.com/gabrielkpo/lifter/issues/36)) ([569f773](https://github.com/gabrielkpo/lifter/commit/569f773386f457802501cbcd7041244d5a5896a3))
* audit log of agent runs, attempts and costs ([#20](https://github.com/gabrielkpo/lifter/issues/20)) ([677b571](https://github.com/gabrielkpo/lifter/commit/677b571bdad0158dc1abf493d294cd4c821eebd0))
* CrossFit domain: cycle, sessions in parts, exercise bank, program loader (step 2) ([#12](https://github.com/gabrielkpo/lifter/issues/12)) ([dbf0e1d](https://github.com/gabrielkpo/lifter/commit/dbf0e1d9c8a367ff97d574c0e98835e7e9923c8c))
* **data:** build the analytics layer with dbt, with contracts and data tests ([#32](https://github.com/gabrielkpo/lifter/issues/32)) ([6b441eb](https://github.com/gabrielkpo/lifter/commit/6b441eb9424ed1bb7e8787c376db1fcfced8844c))
* **db:** role-based access as code, applied by migrate and tested ([#27](https://github.com/gabrielkpo/lifter/issues/27)) ([ebca935](https://github.com/gabrielkpo/lifter/commit/ebca935fc3590eb59afc87599a5819515ddf1fea))
* evaluation bench with 20 scenarios and a copy-last-week baseline ([#16](https://github.com/gabrielkpo/lifter/issues/16)) ([65e736c](https://github.com/gabrielkpo/lifter/commit/65e736ce6429379a176b72daefd30d0a6e5e8d51))
* **ops:** scheduled Garmin sync, daily backup and weekly restore test on the Mac ([#30](https://github.com/gabrielkpo/lifter/issues/30)) ([1da748c](https://github.com/gabrielkpo/lifter/commit/1da748c8a4ff058a72311481a4788432b8b56c70))
* quote check and the guardrail on a stored week, for the coach's write path ([#38](https://github.com/gabrielkpo/lifter/issues/38)) ([0d48e9e](https://github.com/gabrielkpo/lifter/commit/0d48e9ea87e956c7c6842bb673cc1fed11973e2b))
* stop rule in the guardrail, pain above 3/10 means two steps back ([#22](https://github.com/gabrielkpo/lifter/issues/22)) ([2599614](https://github.com/gabrielkpo/lifter/commit/2599614a5b25a6108d9ba14cac2f3d7604a775bd))
* sync Garmin data into Postgres and compute training metrics ([#2](https://github.com/gabrielkpo/lifter/issues/2)) ([6fe7b15](https://github.com/gabrielkpo/lifter/commit/6fe7b153ed86612445ec4574844e29e8003029bc))
* sync Garmin recovery and form data (step 1 bis) ([#9](https://github.com/gabrielkpo/lifter/issues/9)) ([01ef57e](https://github.com/gabrielkpo/lifter/commit/01ef57eb67cf4b438b5d85ac7ddf750983a246b3))
* **sync:** check the schema read-only when the role may not migrate ([#28](https://github.com/gabrielkpo/lifter/issues/28)) ([a1321cd](https://github.com/gabrielkpo/lifter/commit/a1321cdf54dc78ccc6b9ea47ff51a427ebfa980d))
* the agents' audit keeps its full context 90 days, then the metrics only ([#60](https://github.com/gabrielkpo/lifter/issues/60)) ([d6adbb3](https://github.com/gabrielkpo/lifter/commit/d6adbb3a5cfe6f5a53241fdbd72f02a3d43fb70c))
* the coach's write path, a catalogue of operations covering every writable table ([#46](https://github.com/gabrielkpo/lifter/issues/46)) ([7c760eb](https://github.com/gabrielkpo/lifter/commit/7c760eb06b58765425b4a8310fe7b40eb2990909))
* token caps for planner runs, bench passes and model answers ([#33](https://github.com/gabrielkpo/lifter/issues/33)) ([67a1a85](https://github.com/gabrielkpo/lifter/commit/67a1a851001c43332d3c9e0bc84b459e7eecdaf3))
* **web:** deploy on Vercel behind Deployment Protection ([#21](https://github.com/gabrielkpo/lifter/issues/21)) ([78f0b2a](https://github.com/gabrielkpo/lifter/commit/78f0b2ac5abb38fea120406226cedb1c9caae197))
* **web:** floating island tab bar on phones ([#24](https://github.com/gabrielkpo/lifter/issues/24)) ([b0053d4](https://github.com/gabrielkpo/lifter/commit/b0053d4f6bdeb3080d7dd6e660e3efa59a852615))
* **web:** launch screen with falling kettlebells until the first page has its data ([#37](https://github.com/gabrielkpo/lifter/issues/37)) ([1a4533b](https://github.com/gabrielkpo/lifter/commit/1a4533b528884e7864ea30eddf8d8ab4f59e27a5))
* **web:** Lifter logo, a kettlebell with an L, for the tab and home screen icons ([#29](https://github.com/gabrielkpo/lifter/issues/29)) ([50c6794](https://github.com/gabrielkpo/lifter/commit/50c67948b1a8ebe17da8f6c2d479ac663f29ebe5))
* **web:** mobile and desktop PWA with WOD, PRs, planning and health ([#15](https://github.com/gabrielkpo/lifter/issues/15)) ([ca97976](https://github.com/gabrielkpo/lifter/commit/ca97976741c3e133fe3393c96bb71785fc9f70e5))
* **web:** one kettlebell falls, bounces off the floor and the sides, then settles ([#53](https://github.com/gabrielkpo/lifter/issues/53)) ([c7dc155](https://github.com/gabrielkpo/lifter/commit/c7dc1559946229564cbd6a4f9a5a016cda2d90bb))
* **web:** Planning in three views, goals as a table, a shorter splash floor on wide screens ([#66](https://github.com/gabrielkpo/lifter/issues/66)) ([ec08566](https://github.com/gabrielkpo/lifter/commit/ec085663230f05db59e0bd0dee885ab9f128bc89))
* week planner agent with a deterministic guardrail (step 3) ([#14](https://github.com/gabrielkpo/lifter/issues/14)) ([c27b5d1](https://github.com/gabrielkpo/lifter/commit/c27b5d1c12e0fb764d08a60fd4e55af37c490508))


### Bug Fixes

* a bad sync delay or coach language is a setting error, not a crash ([#56](https://github.com/gabrielkpo/lifter/issues/56)) ([78231ed](https://github.com/gabrielkpo/lifter/commit/78231ed4f20192c34f99afccae5fe0939905797b))
* a suggestion made after the athlete's message cannot be accepted with it ([#62](https://github.com/gabrielkpo/lifter/issues/62)) ([a238cfb](https://github.com/gabrielkpo/lifter/commit/a238cfbe34df30d95f86b692146af34740fd0319))
* **agents:** a failure note is hard under an alert, the bench checks two more cases ([#68](https://github.com/gabrielkpo/lifter/issues/68)) ([11937fb](https://github.com/gabrielkpo/lifter/commit/11937fb47cfda786628e91f843e9b1af9be1a03c))
* **agents:** a line without RIR or count no longer escapes the guardrail ([#42](https://github.com/gabrielkpo/lifter/issues/42)) ([ee4cc15](https://github.com/gabrielkpo/lifter/commit/ee4cc1524fa528d1537489cd3213f69ed91e944f))
* **agents:** loads compare in reps only, a plan's notes are never a source ([#45](https://github.com/gabrielkpo/lifter/issues/45)) ([137ced2](https://github.com/gabrielkpo/lifter/commit/137ced2c90fa586ec1e8719c9093cb962cbf757d))
* **agents:** the light-barbell metcon rule covers every exercise on a barbell ([#58](https://github.com/gabrielkpo/lifter/issues/58)) ([9da1fa8](https://github.com/gabrielkpo/lifter/commit/9da1fa822eff26edc39aef9e20dc28fc39af9455))
* **agents:** the planner prompt, tuned on two bench rounds with Mistral ([#71](https://github.com/gabrielkpo/lifter/issues/71)) ([4dfe15e](https://github.com/gabrielkpo/lifter/commit/4dfe15ee66b02a504dfe50b65acaff603b000cfc))
* **agents:** the stop rule caps the whole pattern the painful session loaded ([#44](https://github.com/gabrielkpo/lifter/issues/44)) ([1358c87](https://github.com/gabrielkpo/lifter/commit/1358c872ea0dbed84cf24ca8e0a61ad1607836ce))
* **app:** audit findings on the app and the API ([#39](https://github.com/gabrielkpo/lifter/issues/39)) ([bd1b772](https://github.com/gabrielkpo/lifter/commit/bd1b7729bd768a045dd2a657978edca8530cd38c))
* audit low findings on the app side ([#57](https://github.com/gabrielkpo/lifter/issues/57)) ([fc496f8](https://github.com/gabrielkpo/lifter/commit/fc496f8aaa45388f0d04c67e56676caa8cc98fb4))
* **bench:** reset refuses any database that is not a bench or test one ([#52](https://github.com/gabrielkpo/lifter/issues/52)) ([ae068e5](https://github.com/gabrielkpo/lifter/commit/ae068e5a74a72a71cb93a47198d9bfebea5e0159))
* function words alone justify no change, a negated quote counts for nothing ([#67](https://github.com/gabrielkpo/lifter/issues/67)) ([0f8ba70](https://github.com/gabrielkpo/lifter/commit/0f8ba7037998629eb72fba0aee47fc4b39686316))
* harden the Garmin sync after the step 1 review ([#6](https://github.com/gabrielkpo/lifter/issues/6)) ([e88aacd](https://github.com/gabrielkpo/lifter/commit/e88aacdcff005a78a7d77d252b65e0ab2e4f792a))
* only the message being answered authorises a change, undo survives an agent's run, an applied trace is final ([#72](https://github.com/gabrielkpo/lifter/issues/72)) ([59d6843](https://github.com/gabrielkpo/lifter/commit/59d684311f8a71b15edaf17be3c183210a3c9862))
* **ops:** audit findings on the scheduled jobs ([#40](https://github.com/gabrielkpo/lifter/issues/40)) ([38a0c59](https://github.com/gabrielkpo/lifter/commit/38a0c591ac47b6329b2772040006eb8937f01d33))
* **ops:** back up the conversation under its row-level policies ([#47](https://github.com/gabrielkpo/lifter/issues/47)) ([a738e51](https://github.com/gabrielkpo/lifter/commit/a738e51d8c7b153d3099b06a7163094709e7f634))
* resting HR from daily stats, Garmin status label, readable output ([#11](https://github.com/gabrielkpo/lifter/issues/11)) ([83627fb](https://github.com/gabrielkpo/lifter/commit/83627fb05874069507de4eb4b95e414b76ceef3b))
* secrets stay out of reprs and out of variables dbt could print ([#49](https://github.com/gabrielkpo/lifter/issues/49)) ([6a9405d](https://github.com/gabrielkpo/lifter/commit/6a9405d93d58f0561593694e860bea9d392271da))
* sync and plan-week report outages cleanly, proposals never lack their audit ([#55](https://github.com/gabrielkpo/lifter/issues/55)) ([c412df4](https://github.com/gabrielkpo/lifter/commit/c412df43007d966270d7058c1f5b416965de6223))
* **sync:** a name that does not resolve is an outage, a bad port a setting error ([#69](https://github.com/gabrielkpo/lifter/issues/69)) ([ee3944b](https://github.com/gabrielkpo/lifter/commit/ee3944b441364d74170412ecdf6589b6f6eef49f))
* **sync:** refuse a Garmin MCP URL that would send the token in clear ([#50](https://github.com/gabrielkpo/lifter/issues/50)) ([9052c41](https://github.com/gabrielkpo/lifter/commit/9052c41d9a5b3e76de8cb401b8407944890b8178))
* **sync:** the activity listing stops when the server does not move forward ([#54](https://github.com/gabrielkpo/lifter/issues/54)) ([ec58b36](https://github.com/gabrielkpo/lifter/commit/ec58b36315b17dc785666307e2eacd947cd0ca4e))
* the audit retention is documented as in place, the bench names are exact ([#70](https://github.com/gabrielkpo/lifter/issues/70)) ([8e3cc7e](https://github.com/gabrielkpo/lifter/commit/8e3cc7eadf10c500f6c69633f3023d815aeb55b3))
* **web:** stack session blocks in one column on large screens ([#23](https://github.com/gabrielkpo/lifter/issues/23)) ([5173cac](https://github.com/gabrielkpo/lifter/commit/5173caca71c308afdaf95370ee25657b28f5be6b))
* **web:** the service worker caches nothing and clears old caches ([#26](https://github.com/gabrielkpo/lifter/issues/26)) ([06ae520](https://github.com/gabrielkpo/lifter/commit/06ae52027657fe40387deef29d4bb53d0637b49f))


### Documentation

* add roadmap and data privacy section to README ([#5](https://github.com/gabrielkpo/lifter/issues/5)) ([847df38](https://github.com/gabrielkpo/lifter/commit/847df384280251ae8e54257442de755d80abddc4))
* ADR 0002 accepted by the project owner ([#35](https://github.com/gabrielkpo/lifter/issues/35)) ([61b4e83](https://github.com/gabrielkpo/lifter/commit/61b4e83430a9299a3c8b19dee4d0f61e51250910))
* ADR 0002, the coach in conversation, its write path and the agent team ([#34](https://github.com/gabrielkpo/lifter/issues/34)) ([d78f5ae](https://github.com/gabrielkpo/lifter/commit/d78f5ae5debaf11cbf2684427c53c0cdb0ccb164))
* **agents:** list the free text sent to Mistral by default, and test it ([#48](https://github.com/gabrielkpo/lifter/issues/48)) ([f6cf212](https://github.com/gabrielkpo/lifter/commit/f6cf21254ae741507dd23ff9df767f674044e6f1))
* audit findings on the README and the docs ([#41](https://github.com/gabrielkpo/lifter/issues/41)) ([2250a6c](https://github.com/gabrielkpo/lifter/commit/2250a6cea713e646872313fb105155d381a612e5))
* Mermaid diagrams, example and evaluation plan in the README ([#8](https://github.com/gabrielkpo/lifter/issues/8)) ([a60c5b8](https://github.com/gabrielkpo/lifter/commit/a60c5b887a4c71bed0a6123b4bf9ccb79d9831a7))
* restructure the README to the public repo guide ([#7](https://github.com/gabrielkpo/lifter/issues/7)) ([decb383](https://github.com/gabrielkpo/lifter/commit/decb383ee61dd6605130ee23c3cc5815246003ac))
* say exactly what text goes to Mistral by default ([#51](https://github.com/gabrielkpo/lifter/issues/51)) ([ffe41a1](https://github.com/gabrielkpo/lifter/commit/ffe41a1f5abeb0fef608db4d6fcf063ef9b29531))
* the audit log lives on Neon, its retention is not in place, the bench context ([#59](https://github.com/gabrielkpo/lifter/issues/59)) ([38979c7](https://github.com/gabrielkpo/lifter/commit/38979c7518fbc05b5aebe2984f6487105a407a80))
