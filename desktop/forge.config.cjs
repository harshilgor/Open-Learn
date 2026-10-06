const path = require('node:path');
const owner = process.env.GITHUB_OWNER;
const repository = process.env.GITHUB_REPOSITORY;
const stagedResources = path.join(__dirname, '.vite', 'resources');
const signedRelease = process.env.FORMA_REQUIRE_SIGNING === 'true';
const packageOutput = process.env.FORMA_FORGE_PACKAGE_OUT;

const windowsSigning = signedRelease ? {
  certificateFile: process.env.WINDOWS_CERTIFICATE_FILE,
  certificatePassword: process.env.WINDOWS_CERTIFICATE_PASSWORD,
  description: 'Open Learn',
  website: 'https://github.com/harshilgor/AI-Tutor-Harness-'
} : undefined;

const macSigning = signedRelease ? {
  osxSign: { hardenedRuntime: true },
  osxNotarize: {
    appleId: process.env.APPLE_ID,
    appleIdPassword: process.env.APPLE_APP_SPECIFIC_PASSWORD,
    teamId: process.env.APPLE_TEAM_ID
  }
} : {};

module.exports = {
  packagerConfig: {
    ...(packageOutput ? { out: packageOutput } : {}),
    asar: true,
    name: 'Forma',
    executableName: 'forma',
    appBundleId: 'dev.forma.learning',
    ...(windowsSigning ? { windowsSign: windowsSigning } : {}),
    ...macSigning,
    extraResource: [
      path.join(stagedResources, 'web'),
      path.join(stagedResources, 'backend')
    ]
  },
  rebuildConfig: {},
  makers: [
    {
      name: '@electron-forge/maker-squirrel',
      config: {
        name: 'forma',
        authors: 'Forma Contributors',
        description: 'Local-first AI learning environment',
        ...(windowsSigning ? { windowsSign: windowsSigning } : {})
      }
    },
    { name: '@electron-forge/maker-dmg', platforms: ['darwin'] },
    { name: '@electron-forge/maker-zip', platforms: ['darwin', 'win32'] }
  ],
  ...(owner && repository ? { publishers: [
    { name: '@electron-forge/publisher-github', config: { repository: { owner, name: repository } } }
  ] } : {})
};
