## [1.2.1](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/compare/v1.2.0...v1.2.1) (2026-05-15)


### Bug Fixes

* Add SQLite journal size limit and corresponding test ([f237895](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/f23789570bd655b1f30bb3c15d6813a894f1cadb))
* Add SQLite journal size limit and fix CI issues ([60ceeb1](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/60ceeb17a8fe35415233706698ce4d5ee020b146))

# [1.2.0](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/compare/v1.1.0...v1.2.0) (2026-05-15)


### Bug Fixes

* add 100vh fallback for older browsers ([93b884a](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/93b884a36c736df6126fb5c5df53eb40c8d1ae70))
* address PR review findings — logging, tests, DRY, docs ([9931407](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/993140794ec1fa54138e88ff670182340373dea4))
* clear SQLAlchemy identity map after each writer command ([2e5a957](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/2e5a957c2a27b75ef873e6ad6def070cf154bb85)), closes [#199](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/issues/199)
* cover all env var fields in read-only UI, API stripping, and runtime overlay ([00ae8a6](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/00ae8a63c144e0397381eb0787fc6f81a9d7dfce)), closes [#196](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/issues/196)
* dark mode contrast and readability tweaks ([fa8fa68](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/fa8fa68a0661485a5be4a21ac1db8cef578056c3))
* don't strip out rich html from podcast feeds. ([bdf5f87](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/bdf5f878215b6af58e610624640c391a3dec6784))
* **feeds:** trust upstream <guid> verbatim and self-heal legacy rows ([812c0f6](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/812c0f698b8e0a5ec7d573b95a148fbf005e8f08))
* fix issues with dark mode text input coloring and sub-settings selector ([2358644](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/2358644b04ccaa0f20f6645ef932b4b788581222))
* fix podcast feed spacing on mobile so buttons shapes behave correctly on mobile layouts ([6ba9bf3](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/6ba9bf3c279ff54111b4a0ee9056abb2cb1c394b))
* fix refresh button being hard coded as black, and transparent borders not being transparent in dark mode ([fdb8b94](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/fdb8b9431225a8f95edc2ba3822c1c7f2711d15b))
* Make the first click both reveal the in-page player and actually start playback, instead of needing a second click. ([85e3c25](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/85e3c2502af59ff3d758b6a0b19f8e60f5e8a4b1))
* mark job as failed when all LLM model calls fail during classification ([a5d2da2](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/a5d2da2d43d3007174b9de9057cb2633348c317c))
* merge duplicate ad_segments JSON keys from local LLMs ([5d19488](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/5d194881aee7760e4268f5fc62951676c173e0ab)), closes [#185](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/issues/185)
* only re-queue failed jobs on cleanup and set step_name on cancel ([2f296c1](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/2f296c1f539c52e07f013c9fc8d79c6a1389c82d))
* preserve rich feed HTML while normalizing problematic whitespace, and generate share/feed URLs with the correct HTTPS scheme behind forwarded proxy headers. ([4585ed0](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/4585ed0bde15968aa48160a2ca218a6a132f7a04))
* re-add response_format to ad classification LLM calls ([aa59013](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/aa59013af4bbfebc156009607aca67366e7af632)), closes [#184](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/issues/184)
* resolve NameError and linting issues ([0113a2d](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/0113a2da8affc0014a76fbada419b4bcb2a9ea99))
* revert cleanup re-queue change, keep cancel step_name fixes ([ddf299f](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/ddf299f2ac176b68aba9168beb46e807ecd99ada))
* scope post guid and download_url uniqueness per feed ([8ab6734](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/8ab67340cfa1546702dd876633accbe9a4a74f06)), closes [#186](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/issues/186) [#192](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/issues/192)
* **tests:** stabilize flaky post cleanup tests with explicit file mtimes ([56b0eaf](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/56b0eaf0c83937ba91c718c662b954bb03a9b55e))
* update uv version ([45d68ae](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/45d68ae3e28c9ce11883d7688babc1b5cdc6696b))
* use dvh units to prevent bottom cutoff on Android Chrome ([118c2d6](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/118c2d653f610b35bcb819988a041c863d4f40ca))
* use expunge_all() not expire_all() — actually frees identity map ([e2b89d1](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/e2b89d1ad84a93e1bb6642f43ea68e0030649517))
* use original episode duration for ad percentage and timeline stats ([984f9c7](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/984f9c7ff751c93ca061288ccca0af21cc5c293e))
* use original episode duration for processing cost calculation ([bf9a532](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/bf9a5329724fc8663cc7d2a6c313c70877d0c7ca))


### Features

* add ad merge and profanity detection features in rust sidecar ([3f2d80d](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/3f2d80d5c578965e503eafcd6948fd6b1fadf12d))
* Add audio segment processing for INA analysis ([48a348d](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/48a348da9896640f90bf2ef523a9a4721cfbcc78))
* add bleep padding configuration for output settings and update processing logic ([e2c7615](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/e2c76156df999fe0ad1148b8cda3eeee649fb1c5))
* add build options for AMD64 and ARM64 images in Docker workflow ([af5eb48](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/af5eb484ded7ac5c95f9f677bf2281fe113841ae))
* add debug information for post stats including audio paths and processing details ([6fcc0bc](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/6fcc0bc2089d8dc5221c9cf122045f515ca5a930))
* add display time properties for edited and original audio ranges, update processing logic ([510956b](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/510956b62c44ffecd6a16963e78c17d43cf0ae51))
* add function to refine transcript chapter boundaries and enhance processing logic to ensure blocks are too large in long episodes ([2df470c](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/2df470c085108c21518a73e2bb0818295ba8217c))
* add functionality to cancel all queued jobs with API integration and UI support ([0387ec9](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/0387ec92b82822d1a0e04a1882b9f14fceb03dfc))
* add has_bleep_windows flag and update related components for bleep processing to only show component when there is data ([1147440](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/11474402c751c10b2b38209c3d079045e26fd7c8))
* add LLM chapter fallback tagging configuration and related tests ([aa45d06](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/aa45d06050aa43069fd37d35f4cd82f44c067a74))
* add manual workflow inputs for Docker image builds and update conditions for job execution ([6d448d1](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/6d448d112d6a866a452d78dc26eac93277221768))
* Add Sorting Behavior to the podcast feed ([a0b6119](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/a0b6119a11f59550ba98e568c7d845ac5ec06506))
* Add speaker label support and integration settings ([885daba](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/885dabaebcc623270aca3934f4e3c9770e910c0f))
* add stage history tracking to processing jobs ([d52985d](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/d52985df4e5fb35aaeef1fee9c358f5aa95802ef))
* add transcript word timestamps caching and processing improvements ([3de8543](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/3de8543d8497f1977bc36c4943d2bb3d95445124))
* Enhance ad segment processing with edge audio expansion and refined boundary handling ([f946107](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/f9461078314be9a7d7184f844f86db5d8b2ff418))
* enhance audio processing and duration handling across routes and models ([e2f754b](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/e2f754b83819153c693dd5e3eba60532ce527721))
* enhance audio processing with bitrate options and lossless trimming, update tests for new encoding args ([d88b213](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/d88b213d7bd66efe04ad3409f9aa0768eec21df9))
* enhance feed settings handling with chapter fallback logic and validation ([f481d00](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/f481d009fb7dc4b4aa38fb97dc8d1e46a064b6cf))
* enhance processing stats with edited duration and timeline markers for ads and bleeps ([bddae5e](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/bddae5e826cf499713cda7f825d316176e099bd3))
* Extend chapter timestamps to cover entire audio duration for compatibility with podcast players ([931ae75](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/931ae755c98ffb1a695993760b40e96fb5261c49))
* **frontend:** add persisted dark mode toggle and contrast fixes ([0cda964](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/0cda964943e36eb704e4daef55eb03eaa5bb0b88))
* Implement admin cost dashboard and feed subscriber view with new job management actions. ([e3afea6](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/e3afea6e7023948b33c71eacc2b2695fb0e2005c))
* implement audio path resolution in JobManager and add unit tests for validation logic ([6318fd1](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/6318fd1026a4f7c0f0c5eef91f10aa2c8de39bd4))
* Implement audio segment bridging and extraction for improved ad detection ([6ab6110](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/6ab611085647cb4455acfa7755d4c8a16d18fd52))
* implement chunk progress callback for transcription process and update related tests ([9c7a706](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/9c7a706e58235689c1864fa74763c1cf0c32788a))
* Implement feed refresh planning with Rust integration ([3890bf5](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/3890bf5adcd8bce7465a48ac5bd09d09a955a825))
* implement find_existing_processed_audio_path utility and refactor audio path handling in jobs manager and cleanup actions ([c96f183](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/c96f183c007d7d2730dea5f21609d47fc33f7c54))
* implement memory management enhancements with context-aware memory trimming ([3fca154](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/3fca154c441d1eee403752cd4a5d07be4df9eef7))
* implement per-job processing worker and memory management improvements ([72a6ffa](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/72a6ffa51bea174216023abe88f0100eb8e4ad6d))
* Implement profanity filtering and bleeping functionality ([b4b25e8](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/b4b25e818c18f24c8ae0ca3fa56341d1d4d053d5))
* Implement zero-ads guard with auto-retry mechanism ([9b7d543](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/9b7d5433c7995d535aa350705fae81a19916ced5))
* integrate chapter data fetching and improve audio player functionality ([8acbced](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/8acbced83b25f89c0543ac1ed4eb6f3f75406d39))
* Integrate Rust sidecar for audio processing and feed generation ([b24e401](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/b24e401ad3c4486d6e0cf898840c6502d3e99d0d))
* introduce configurable cost rate per hour setting in app configuration. ([72c7f39](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/72c7f39cd251606c0f5484df15468a737b63341e))
* make env vars authoritative over database config ([9a97c51](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/9a97c51bd78a9888368b0d7367591fc15f65ef67)), closes [#190](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/issues/190)
* reduce job status refresh interval from 3000ms to 1000ms for improved responsiveness ([a632d93](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/a632d9367452e65639bfaeefcc3e6745e3f03c50))
* simplify conditional checks for Docker build jobs and add variant selection logic ([c66a2ec](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/c66a2eccd286b8a4f92bf10f4c7e6760f8d775e0))
* Update API routes to accept GUIDs with slashes and enhance test coverage ([e441c27](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/e441c271d97f05f217f2d552196853c975eaee77))
* update chapter tagging work with more podcast players, implement multi-pass audio bleeping to prevent ffmpeg issues, mute audio entirely instead of duck, and add chapter duration clamping ([cb239b7](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/cb239b7659c4487b7a3c997d62f8b9070345f74c))


### Performance Improvements

* **feed:** drop synchronous refresh_feed from GET /feed/<id> ([bef20fd](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/bef20fd03bfff9597f3defe4ca4deb068b4b9ef9))
* **feed:** short-circuit unchanged feeds with ETag/Last-Modified 304s ([679694e](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/commit/679694e023ffe0dd7ba6c702d26eec7b6e85a523))
