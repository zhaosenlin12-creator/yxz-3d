import { mergeConfigs, presetWebFonts } from 'unocss'

import { presetWebFontsFonts, sharedUnoConfig } from '../../uno.config'

export default mergeConfigs([
  sharedUnoConfig(),
  {
    presets: [
      presetWebFonts({
        fonts: {
          // Provider "fontsource" links the font files to cdn.jsdelivr.net.
          // That CDN is unreachable from a lot of Chinese networks (and from
          // any exhibition machine without internet), so the request either
          // hangs or is reset and the page paints late.  The fonts are
          // self-hosted in public/fonts instead -- see
          // scripts/self-host-fonts.mjs and src/styles/self-hosted-fonts.css.
          ...presetWebFontsFonts('none'),
        },
        timeouts: {
          warning: 5000,
          failure: 10000,
        },
      }),
    ],
    rules: [
      ['transition-colors-none', {
        'transition-property': 'color, background-color, border-color, text-color',
        'transition-duration': '0s',
      }],
    ],
  },
])
