# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- MIT `LICENSE` for this project's own application code (third-party
  packages and models keep their own terms; see the README).
- README status badges.
- This changelog.

## [1.0.1] - 2026-11-09

### Fixed

- PNG palette and color-key transparency is now composited correctly before
  analysis (#3).

## [1.0.0] - 2026-11-09

### Added

- FastAPI service returning image analysis from NudeNet, the Freepik NSFW
  Image Detector and optional Project Arachnid Shield; CPU only.
- HTTPS image URL scanning with optional exact-hostname restrictions and
  network safeguards (#1).
- Documentation explaining nudity signals and known-content match results.
- Independent Vultr image processor with local ClamAV (#2).
- GitHub Actions workflow building a multi-platform (linux/amd64,
  linux/arm64) Docker image on release tags and pushing it to Docker Hub.

### Changed

- Cross-service multipart test fixture is now reproducible.

[Unreleased]: https://github.com/repasscloud/image-moderation-api/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/repasscloud/image-moderation-api/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/repasscloud/image-moderation-api/releases/tag/v1.0.0
