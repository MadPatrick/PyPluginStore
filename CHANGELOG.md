# Changelog

## [2.17.1](https://github.com/adrighem/PyPluginStore/compare/v2.17.0...v2.17.1) (2026-07-15)


### Bug Fixes

* align local badge with platforms ([6e89809](https://github.com/adrighem/PyPluginStore/commit/6e898091ff3a95edcf34a76a925901bc888d8592)), closes [#98](https://github.com/adrighem/PyPluginStore/issues/98)

## [2.17.0](https://github.com/adrighem/PyPluginStore/compare/v2.16.1...v2.17.0) (2026-07-14)


### Features

* update Domoticz Python plugin registry ([fcba4a6](https://github.com/adrighem/PyPluginStore/commit/fcba4a621018f6eb6169776d57b010577f32cf27))


### Bug Fixes

* align WeatherInfo registry metadata ([cb7e6cf](https://github.com/adrighem/PyPluginStore/commit/cb7e6cfc8b083c63613099eb1a0bd0af199922fb))
* bound registry git validation ([c4ea849](https://github.com/adrighem/PyPluginStore/commit/c4ea849c36ac06684ec54abc3824fecbea8e5584))
* retry transient registry fetches ([7adaadd](https://github.com/adrighem/PyPluginStore/commit/7adaadd655781305fcd81858984a229c31cad505))

## [2.16.1](https://github.com/adrighem/PyPluginStore/compare/v2.16.0...v2.16.1) (2026-07-09)


### Bug Fixes

* keep API payload device disabled ([11d2e0b](https://github.com/adrighem/PyPluginStore/commit/11d2e0ba2b0bbf52da3f1c4c2a7a23daea434656))
* report stale self-update git lock ([7029eed](https://github.com/adrighem/PyPluginStore/commit/7029eeddecfe8e8857f5c1bd660f45e991ed8c04)), closes [#94](https://github.com/adrighem/PyPluginStore/issues/94)
* track PyPluginStore self-update state ([f1d5a2c](https://github.com/adrighem/PyPluginStore/commit/f1d5a2c37da56efe2e179afa44bd882b38f5ed67)), closes [#94](https://github.com/adrighem/PyPluginStore/issues/94)

## [2.16.0](https://github.com/adrighem/PyPluginStore/compare/v2.15.2...v2.16.0) (2026-07-08)


### Features

* native theme support, version 1 ([21387b0](https://github.com/adrighem/PyPluginStore/commit/21387b0261280143976c730346fab089857e4495))


### Bug Fixes

* accept API bridge error responses ([7be417c](https://github.com/adrighem/PyPluginStore/commit/7be417c6bf3d33e9c6eb02ead43cc8b63fd0d9d0))
* align local override branch metadata ([fbeb52c](https://github.com/adrighem/PyPluginStore/commit/fbeb52ce8143de6e67a4ccc405d9dcc8dc714259)), closes [#73](https://github.com/adrighem/PyPluginStore/issues/73)
* align plugin card badges ([e7b12ad](https://github.com/adrighem/PyPluginStore/commit/e7b12ad67883ec6ca167df4487e4ca6d387fdfea)), closes [#92](https://github.com/adrighem/PyPluginStore/issues/92)
* default plugin store to Domoticz theme layout ([865cd79](https://github.com/adrighem/PyPluginStore/commit/865cd79b02aa92c31924f918a145a2b9fb6a013d)), closes [#91](https://github.com/adrighem/PyPluginStore/issues/91)
* fine-tune Domoticz theme support ([ed365ae](https://github.com/adrighem/PyPluginStore/commit/ed365ae3813811026e877f8298bd0982bd274764)), closes [#91](https://github.com/adrighem/PyPluginStore/issues/91)
* warn on installed registry mismatches ([1e0e4e2](https://github.com/adrighem/PyPluginStore/commit/1e0e4e2270c5528e9982c268b874c3cc55b0d837)), closes [#73](https://github.com/adrighem/PyPluginStore/issues/73)


### Documentation

* add registry_local how-to ([434922b](https://github.com/adrighem/PyPluginStore/commit/434922bdd5f6c18ccf9872e4e976a438163f0bf4))
* clarify repo mismatch recovery ([d1a9b49](https://github.com/adrighem/PyPluginStore/commit/d1a9b496116645d3e3626d8c142407c9c99c7243)), closes [#73](https://github.com/adrighem/PyPluginStore/issues/73)
* document repo mismatch warning ([03e3c71](https://github.com/adrighem/PyPluginStore/commit/03e3c713e3c2bb360c0758435a14652487c01c0a)), closes [#73](https://github.com/adrighem/PyPluginStore/issues/73)
* move local registry guidance to configuration ([0d3bade](https://github.com/adrighem/PyPluginStore/commit/0d3bade345bef80f2578bb11d023d8296ba8229f))

## [2.15.2](https://github.com/adrighem/PyPluginStore/compare/v2.15.1...v2.15.2) (2026-07-05)


### Bug Fixes

* harden weekly plugin discovery ([24a63df](https://github.com/adrighem/PyPluginStore/commit/24a63df202e0b83668e97d98106a1765076929d4)), closes [#88](https://github.com/adrighem/PyPluginStore/issues/88)
* stabilize API error responses ([87a8bd8](https://github.com/adrighem/PyPluginStore/commit/87a8bd8aab8b13c03c27a2b0ed0e47bd1918da6a))


### Documentation

* record theme management maintainer notes ([2b07ef5](https://github.com/adrighem/PyPluginStore/commit/2b07ef59989d49d2a3fd278fad86a1f18ad9c64d)), closes [#30](https://github.com/adrighem/PyPluginStore/issues/30) [#87](https://github.com/adrighem/PyPluginStore/issues/87)

## [2.15.1](https://github.com/adrighem/PyPluginStore/compare/v2.15.0...v2.15.1) (2026-07-04)


### Bug Fixes

* align self update git ownership handling ([a9de821](https://github.com/adrighem/PyPluginStore/commit/a9de82121d4de602ac4fec15b3bd2b901a4962e2)), closes [#86](https://github.com/adrighem/PyPluginStore/issues/86)
* avoid ownership repair for managed git repos ([fd284e7](https://github.com/adrighem/PyPluginStore/commit/fd284e7413b7e3b12ff32ba976071bc45fcfa9bf)), closes [#86](https://github.com/adrighem/PyPluginStore/issues/86)
* clarify git ownership diagnostics ([10432fb](https://github.com/adrighem/PyPluginStore/commit/10432fbf4eb52e2823689ca05f58a08af367e53d)), closes [#86](https://github.com/adrighem/PyPluginStore/issues/86)
* prune stale update times during registry scans ([2c94c69](https://github.com/adrighem/PyPluginStore/commit/2c94c6939fc1ad72089d49312fbb4610341cad4f)), closes [#84](https://github.com/adrighem/PyPluginStore/issues/84)


### Documentation

* update issue 86 investigation note ([6156dff](https://github.com/adrighem/PyPluginStore/commit/6156dff64b0e389c89ff2d96f0c40f8444dcbfca)), closes [#86](https://github.com/adrighem/PyPluginStore/issues/86)

## [2.15.0](https://github.com/adrighem/PyPluginStore/compare/v2.14.2...v2.15.0) (2026-07-02)


### Features

* support Codeberg and GitLab plugin repositories ([8a55c7c](https://github.com/adrighem/PyPluginStore/commit/8a55c7c5a7461291152e7321522f512c7aff3dff)), closes [#76](https://github.com/adrighem/PyPluginStore/issues/76)
* update Domoticz Python plugin registry ([9342d41](https://github.com/adrighem/PyPluginStore/commit/9342d41d91aa055a489ec92bd69e41a3c9ddb649))


### Bug Fixes

* make plugin store repository links host-aware ([25d6ad1](https://github.com/adrighem/PyPluginStore/commit/25d6ad1e93874bc63bb8baba6204fc0783c04ee2)), closes [#76](https://github.com/adrighem/PyPluginStore/issues/76)
* preserve registry branches during scans ([8dc31d3](https://github.com/adrighem/PyPluginStore/commit/8dc31d3a5714dc89db1e0620b0ca331ead1c35c8))
* stabilize platform detection metadata ([e13d5b9](https://github.com/adrighem/PyPluginStore/commit/e13d5b94ac00a79ecd08454f19e390b19df81c94))

## [2.14.2](https://github.com/adrighem/PyPluginStore/compare/v2.14.1...v2.14.2) (2026-07-02)


### Bug Fixes

* add non-git badges and implement branch-aware updates (fixes [#73](https://github.com/adrighem/PyPluginStore/issues/73), closes [#74](https://github.com/adrighem/PyPluginStore/issues/74)) ([73b0c1c](https://github.com/adrighem/PyPluginStore/commit/73b0c1c40152a68d2059bf5d4a0a115c762e14d6))
* **updater:** upgrade to robust fetch-and-reset updater sequence (fixes [#73](https://github.com/adrighem/PyPluginStore/issues/73)) ([0b6b003](https://github.com/adrighem/PyPluginStore/commit/0b6b0032123a760a01f2a01f3118e17d0652f440))

## [2.14.1](https://github.com/adrighem/PyPluginStore/compare/v2.14.0...v2.14.1) (2026-07-01)


### Bug Fixes

* bypass Git dubious ownership with safe.directory option ([3292bbb](https://github.com/adrighem/PyPluginStore/commit/3292bbb564d2c040886a76358819154f054d9fe0)), closes [#70](https://github.com/adrighem/PyPluginStore/issues/70)

## [2.14.0](https://github.com/adrighem/PyPluginStore/compare/v2.13.1...v2.14.0) (2026-06-29)


### Features

* add Luxtronik Windows platform ([1814323](https://github.com/adrighem/PyPluginStore/commit/1814323c08066aafacaed7574a288fb7c5ff930c)), closes [#66](https://github.com/adrighem/PyPluginStore/issues/66)


### Bug Fixes

* harden self-update preflight ([28c7f43](https://github.com/adrighem/PyPluginStore/commit/28c7f4343ea4d3a4266f18e72107cf0c28b0cf8d)), closes [#65](https://github.com/adrighem/PyPluginStore/issues/65)
* recover from Git ownership mismatch ([e0de2a6](https://github.com/adrighem/PyPluginStore/commit/e0de2a6475c26ad8bcb905489beba9b9498d3bce)), closes [#69](https://github.com/adrighem/PyPluginStore/issues/69)

## [2.13.1](https://github.com/adrighem/PyPluginStore/compare/v2.13.0...v2.13.1) (2026-06-29)


### Bug Fixes

* avoid self-update API timeout ([47e2d73](https://github.com/adrighem/PyPluginStore/commit/47e2d7380c2b53841fa587ca53e53d2056cbd3f5)), closes [#65](https://github.com/adrighem/PyPluginStore/issues/65)

## [2.13.0](https://github.com/adrighem/PyPluginStore/compare/v2.12.1...v2.13.0) (2026-06-29)


### Features

* add Domoticz-Home-Connect-Plugin & implement lightweight version visibility in UI ([8c8c519](https://github.com/adrighem/PyPluginStore/commit/8c8c519b2dbf85270265398481265ea76e379f98))

## [2.12.1](https://github.com/adrighem/PyPluginStore/compare/v2.12.0...v2.12.1) (2026-06-28)


### Bug Fixes

* clean API bridge payloads ([66ae709](https://github.com/adrighem/PyPluginStore/commit/66ae709eb8cb833baff986be03ae705d49f4778b))


### Documentation

* add clear installation and configuration checks ([d451fda](https://github.com/adrighem/PyPluginStore/commit/d451fda374bce6b59a43d8bbeef2945fed89bd0d))

## [2.12.0](https://github.com/adrighem/PyPluginStore/compare/v2.11.1...v2.12.0) (2026-06-28)


### Features

* infer plugin platform metadata ([24c0d12](https://github.com/adrighem/PyPluginStore/commit/24c0d1226bff620a6c9a57825240df0a9155a2ae))
* remember installed filter state ([52fb697](https://github.com/adrighem/PyPluginStore/commit/52fb697f4c30409963c1de898c46e6ed873dc3f9))
* update Domoticz Python plugin registry ([d0950bb](https://github.com/adrighem/PyPluginStore/commit/d0950bbbf278743f8831510541e9af96fe068d02))


### Bug Fixes

* cache startup update status ([f3686ad](https://github.com/adrighem/PyPluginStore/commit/f3686ad6ce0197f7e191ce08fecc3eee5512fc9b))
* detect Marstek Modbus plugin ([88227a2](https://github.com/adrighem/PyPluginStore/commit/88227a236a062a9d9192c9646fdae8f249609da3))
* find hidden api bridge devices ([fe16a46](https://github.com/adrighem/PyPluginStore/commit/fe16a463704bbb0aec5b695c1671bebf4b8d2413))
* improve plugin discovery and UI bridge ([21cd308](https://github.com/adrighem/PyPluginStore/commit/21cd3081542a62fe4a122f2e7592e2c679e7692a))
* improve restart permission diagnostics ([7b815b0](https://github.com/adrighem/PyPluginStore/commit/7b815b0a02bcb7bf3e464b1b7eaa8ddd8d76809b))
* support domoticz without notification api ([d876414](https://github.com/adrighem/PyPluginStore/commit/d876414a6edd0e05220568ab13b3e277bc085f53))

## [2.11.1](https://github.com/adrighem/PyPluginStore/compare/v2.11.0...v2.11.1) (2026-06-27)


### Bug Fixes

* improve installed plugin detection ([1395e55](https://github.com/adrighem/PyPluginStore/commit/1395e55dea63062573dc1104ecae465c79584ecf))

## [2.11.0](https://github.com/adrighem/PyPluginStore/compare/v2.10.0...v2.11.0) (2026-06-26)


### Features

* detect pre-existing plugin installs ([4cdf56a](https://github.com/adrighem/PyPluginStore/commit/4cdf56a2345a11df5571f0d860722345701b12fa))

## [2.10.0](https://github.com/adrighem/PyPluginStore/compare/v2.9.1...v2.10.0) (2026-06-26)


### Features

* add Windows support runtime ([3bab033](https://github.com/adrighem/PyPluginStore/commit/3bab03358e5f99fa42d04848eacf626689ec045a))

## [2.9.1](https://github.com/adrighem/PyPluginStore/compare/v2.9.0...v2.9.1) (2026-06-22)


### Bug Fixes

* install custom UI icon under Domoticz images ([84eb18e](https://github.com/adrighem/PyPluginStore/commit/84eb18ebb7d2a1d51d1a4ba179cca64e078fb87d))


### Documentation

* document release-please commit requirements ([abb8bd8](https://github.com/adrighem/PyPluginStore/commit/abb8bd86a7fee2e57fe5d228dfbb094b1e022772))

## [2.9.0](https://github.com/adrighem/PyPluginStore/compare/v2.8.2...v2.9.0) (2026-06-21)


### Features

* add new Domoticz Python plugins ([4c2fa40](https://github.com/adrighem/PyPluginStore/commit/4c2fa406f1a795e97c32783c084ce539532985bd))


### Documentation

* refine README logo presentation ([79c1911](https://github.com/adrighem/PyPluginStore/commit/79c1911a6290b70c3e52b39cbe919c172a0e59f7))
* rename store screenshot asset ([dbe78fc](https://github.com/adrighem/PyPluginStore/commit/dbe78fc15582c91d4dd97286cd9aaf4bb70eca5e))
* update README wording ([04216d1](https://github.com/adrighem/PyPluginStore/commit/04216d190d9ff89c9c293a3d8d8f15f6d81e6370))

## [2.8.2](https://github.com/adrighem/PyPluginStore/compare/v2.8.1...v2.8.2) (2026-06-21)


### Bug Fixes

* apply MadPatrick registry refresh intent ([c88f4d3](https://github.com/adrighem/PyPluginStore/commit/c88f4d319a41f2c3fe679e90cbe0af277a3148ef))

## [2.8.1](https://github.com/adrighem/PyPluginStore/compare/v2.8.0...v2.8.1) (2026-06-20)


### Bug Fixes

* parse clone URLs before GitHub normalization ([66bcd4c](https://github.com/adrighem/PyPluginStore/commit/66bcd4ca598d8ea06fdcd05e817e3c85bb2489c9))

## [2.8.0](https://github.com/adrighem/PyPluginStore/compare/v2.7.0...v2.8.0) (2026-06-20)


### Features

* support local registry overlays with MadPatrick ([36f3bcf](https://github.com/adrighem/PyPluginStore/commit/36f3bcf79bbdc942999517f55e074a3d0a0653e8))


### Bug Fixes

* remove unavailable Melotron Python registry entry ([e6d98c8](https://github.com/adrighem/PyPluginStore/commit/e6d98c83da45c39c9015763ded6133c1810e1e25))

## [2.7.0](https://github.com/adrighem/PyPluginStore/compare/v2.6.0...v2.7.0) (2026-06-15)


### Features

* add plugin update controls and cached status refresh with MadPatrick ([81018ad](https://github.com/adrighem/PyPluginStore/commit/81018adcdc9662dfaefec07737db566c34f26f2a))


### Bug Fixes

* clean plugin update time refresh ([86c0c6a](https://github.com/adrighem/PyPluginStore/commit/86c0c6a3bb92ef60a6a8331062e16a93ca2ae8b7))


### Documentation

* clarify generated plugin workflow ([39dd23a](https://github.com/adrighem/PyPluginStore/commit/39dd23a2bd6472de4b39e264d4d1339bcb2022df))

## [2.6.0](https://github.com/adrighem/PyPluginStore/compare/v2.5.0...v2.6.0) (2026-06-14)


### Features

* MadPatrick: Change layout to new Domoticz style
* clean Domoticz affixes from plugin cards ([4b5e805](https://github.com/adrighem/PyPluginStore/commit/4b5e805a8eed1e2b2fa06d18bf50d666462d9ba4))
* improve plugin store controls ([2c102a2](https://github.com/adrighem/PyPluginStore/commit/2c102a212fa244734850413f9c5b0ef1810a6888))


### Bug Fixes

* block core Domoticz repository from registry ([f0693d6](https://github.com/adrighem/PyPluginStore/commit/f0693d614b39c5e36cd076fa6a43d4525b890f50))
* harden plugin scanner registry updates ([80853e1](https://github.com/adrighem/PyPluginStore/commit/80853e1931c05ba5b01f327d7e87ad4b355e42b2))
* remove empty repositories from registry ([ed49951](https://github.com/adrighem/PyPluginStore/commit/ed49951fa6f3976d2875c14c7d8b5f31d1416f6e))
* restore update button colors after MadPatrick layout refresh ([c9d4fd1](https://github.com/adrighem/PyPluginStore/commit/c9d4fd169271b8f1e0a258bbe8f7584a778946b4))
* restore update button state colors ([eb66ded](https://github.com/adrighem/PyPluginStore/commit/eb66ded97bc4308b4e44952fc5758b29fcdf782f))
* skip empty repositories in plugin scanner ([293429b](https://github.com/adrighem/PyPluginStore/commit/293429bac3e159243a2f0a270edb75259b807919))
* strip domoticz-for card title affixes ([251545e](https://github.com/adrighem/PyPluginStore/commit/251545ebe8ef68229da4d75e7e70fbc133e2c76e))


### Documentation

* update store screenshot ([b4e2772](https://github.com/adrighem/PyPluginStore/commit/b4e2772fa9817fc834d3f914bc0d78ca85a1890a))

## [2.5.0](https://github.com/adrighem/PyPluginStore/compare/v2.4.0...v2.5.0) (2026-06-07)


### Features

* add new Domoticz Python plugins ([e414b40](https://github.com/adrighem/PyPluginStore/commit/e414b4095cfb601be8ea2febcce28671d0bece5a))

## [2.4.0](https://github.com/adrighem/PyPluginStore/compare/v2.3.0...v2.4.0) (2026-06-03)


### Features

* add new Domoticz Python plugins ([40e1bf9](https://github.com/adrighem/PyPluginStore/commit/40e1bf91eeb1cf28ce81c54fd727198456133be0))
* split plugin last updated dates into update_times.json ([0eabae9](https://github.com/adrighem/PyPluginStore/commit/0eabae96c6adb9b45b226790409d6094d734ea3b))


### Bug Fixes

* remove deleted tado_domoticz plugin ([0eff094](https://github.com/adrighem/PyPluginStore/commit/0eff094eb25db7326d8e5453da43d055299ff7c7))

## [2.3.0](https://github.com/adrighem/PyPluginStore/compare/v2.2.2...v2.3.0) (2026-05-12)


### Features

* improve github scanner robustness and add missing plugins ([7794c14](https://github.com/adrighem/PyPluginStore/commit/7794c14e57243b16345885d3ea2bcd20e6b913d2))

## [2.2.2](https://github.com/adrighem/PyPluginStore/compare/v2.2.1...v2.2.2) (2026-05-12)


### Bug Fixes

* correct UI mapping for card title and description ([e8000f2](https://github.com/adrighem/PyPluginStore/commit/e8000f28d4a7a40448ea93a9aad9adcb234bce21))

## [2.2.1](https://github.com/adrighem/PyPluginStore/compare/v2.2.0...v2.2.1) (2026-05-11)


### Bug Fixes

* correct capitalization in javascript getElementById ([3c55090](https://github.com/adrighem/PyPluginStore/commit/3c550904126cd31880ce9aa1a98437043812d300))
* remove pp-manager from registry and ignore in monthly scans ([5a7003a](https://github.com/adrighem/PyPluginStore/commit/5a7003a36a1dede054adb13383e86cc7aa9faa88))
* revert plugin key to PP-MANAGER for hardware backward compatibility and remove legacy UI ([68bfbc7](https://github.com/adrighem/PyPluginStore/commit/68bfbc7a807b16e4abae87b4bf7f3d1da31fde07))


### Documentation

* update store screenshot with new PyPluginStore UI ([1f61e6f](https://github.com/adrighem/PyPluginStore/commit/1f61e6f840afee27af928b88e29302d4169d0d88))

## [2.2.0](https://github.com/adrighem/PyPluginStore/compare/v2.1.0...v2.2.0) (2026-05-11)


### Features

* add KPN Experia v10 plugin to registry ([290a08e](https://github.com/adrighem/PyPluginStore/commit/290a08ed7470f415f76a4b4910b4a7e45230d78b))


### Bug Fixes

* revert original repo name and url in fork note and registry ([ad0b51d](https://github.com/adrighem/PyPluginStore/commit/ad0b51df380634743ceeb723e19a114a261f1ee7))

## [2.1.0](https://github.com/adrighem/PyPluginStore/compare/v2.0.0...v2.1.0) (2026-05-10)


### Features

* add 'Repo' button to plugin cards ([8cd1389](https://github.com/adrighem/PyPluginStore/commit/8cd138955799bc793facd69cb81763e06334970e))
* add new Domoticz Python plugins ([c67a813](https://github.com/adrighem/PyPluginStore/commit/c67a8135c3c1d2ee9822acf9895ecbf15b29cb88))
* add new Domoticz Python plugins ([03b13e4](https://github.com/adrighem/PyPluginStore/commit/03b13e4dcb92737356fc248a6298cfbb07de8a3b))
* add search filter and installed-only toggle to dashboard ([7e25c1f](https://github.com/adrighem/PyPluginStore/commit/7e25c1fd8e0e96bd7d866fc5b6cbe62794227ad5))
* implement device bus API and custom HTML dashboard ([01ca5ef](https://github.com/adrighem/PyPluginStore/commit/01ca5efb29232a5619bb202059acff1859d00261))
* improve custom UI autoinstall logic ([5951e29](https://github.com/adrighem/PyPluginStore/commit/5951e2907732723409460c0276a3e303535ddb6d))
* make security scanner smarter by ignoring private IPs and targeting high-risk subprocess calls ([283e0b6](https://github.com/adrighem/PyPluginStore/commit/283e0b635d0c55e209209fa05c06d00164187b32))
* overhaul monthly scan to sync full registry and show 'last updated' in UI ([6cbf85e](https://github.com/adrighem/PyPluginStore/commit/6cbf85efb4583dd275b26eff944ed4f16192db7b))


### Bug Fixes

* add cache busters and absolute paths to API calls ([e74bda8](https://github.com/adrighem/PyPluginStore/commit/e74bda8ecd7aefe0cd5b01b2effe1dcfc377c5e9))
* call init directly to support SPA injection ([f6da725](https://github.com/adrighem/PyPluginStore/commit/f6da725bd1f3316c865180c11fcfe1b7b0d32747))
* echo back tx_id in API responses to unblock frontend polling ([f7f1476](https://github.com/adrighem/PyPluginStore/commit/f7f1476e6cc9f711d716953b31e2108d84360d88))
* ignore version-like strings that look like IPs in User Agents ([08c386b](https://github.com/adrighem/PyPluginStore/commit/08c386b81ef27620efe3ba8d73c42c8748a8a179))
* refactor HTML to snippet and improve SPA init logic ([bab35ca](https://github.com/adrighem/PyPluginStore/commit/bab35caa6bcdeb0c19ee01a8ada2f7631209d787))
* refactor Repo button to simple anchor link ([2821b24](https://github.com/adrighem/PyPluginStore/commit/2821b24af9085886c622e98466e732751153291a))
* refine scanner to ignore version-like IPs and safe json.loads calls ([6fcb4b0](https://github.com/adrighem/PyPluginStore/commit/6fcb4b034ab8279a11210fee531f4d4ffdeceb00))
* resolve NameError for datetime and json imports ([4a6f748](https://github.com/adrighem/PyPluginStore/commit/4a6f748a0ac517bc444fb484a650c317563331b4))
* resolve NameError for home_folder in installDependencies ([15e8709](https://github.com/adrighem/PyPluginStore/commit/15e87091f24e0a6cd0829267a161da5dd12a5d1b))
* resolve XML encoding issue in plugin generator ([b48c517](https://github.com/adrighem/PyPluginStore/commit/b48c5172dc8bee841415e6b9edc27411e20b93e6))
* restore method indentation for is_private_ip ([540627c](https://github.com/adrighem/PyPluginStore/commit/540627cbb3038cd0b0f79b0328fcacbf6aad8005))
* revert to relative paths for subpath support ([facdfa2](https://github.com/adrighem/PyPluginStore/commit/facdfa254825c1096fe29d2377c7502d46e85761))
* update polling to use modern getdevices API syntax ([5c5b9c3](https://github.com/adrighem/PyPluginStore/commit/5c5b9c3089c8b62ba0a9803727bb9a7909c7c183))


### Documentation

* rename dashboard screenshot and update README with new UI instructions ([3130628](https://github.com/adrighem/PyPluginStore/commit/3130628212095524f18c3f67ea3e8ce5debbf8a1))

## [2.0.0](https://github.com/adrighem/PyPluginStore/compare/v1.5.47...v2.0.0) (2026-04-06)


### ⚠ BREAKING CHANGES

* configure release-please to start at 2.0.0 and update plugin files

### Features

* add monthly github action to discover domoticz plugins ([a3dd3df](https://github.com/adrighem/PyPluginStore/commit/a3dd3dff5e13045ebcf0bf60e67024573c7a7c30))
* bump version to 2.0.0 and add release-please workflow ([dce185b](https://github.com/adrighem/PyPluginStore/commit/dce185b34bb9280008a5aea551f94e6487ad862c))
* configure release-please to start at 2.0.0 and update plugin files ([d24f894](https://github.com/adrighem/PyPluginStore/commit/d24f894cad3f6aa4acd71d924be7046367fa69b6))


### Documentation

* update forum link in README ([871a666](https://github.com/adrighem/PyPluginStore/commit/871a666467a13ec764f927cd3ecbb3365560b1cd))
