const { skeleton } = require('@skeletonlabs/tw-plugin');
const forms = require('@tailwindcss/forms');

module.exports = {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
      fontFamily: {
        display: ['"Space Grotesk"', 'Inter', 'system-ui', 'sans-serif'],
        body: ['"Inter"', 'system-ui', 'sans-serif']
      },
      boxShadow: {
        glow: '0 18px 60px rgba(0, 0, 0, 0.35)'
      }
    }
  },
  plugins: [
    forms,
    skeleton({
      themes: {
        preset: ['modern'],
        extend: {
          jamarr: {
            name: 'jamarr',
            properties: {
              '--theme-font-family-base': '"Inter", system-ui, sans-serif',
              '--theme-font-family-heading': '"Space Grotesk", "Inter", system-ui, sans-serif',
              '--theme-rounded-base': '14px',
              '--theme-rounded-container': '18px',
              '--theme-border-base': '1px',
              '--on-primary': '0 0 0',
              '--on-secondary': '255 255 255',
              '--on-tertiary': '255 255 255',
              '--on-success': '0 0 0',
              '--on-warning': '0 0 0',
              '--on-error': '255 255 255',
              '--on-surface': '255 255 255',
              '--color-primary-50': '239 246 255',
              '--color-primary-100': '219 234 254',
              '--color-primary-200': '191 219 254',
              '--color-primary-300': '147 197 253',
              '--color-primary-400': '96 165 250',
              '--color-primary-500': '59 130 246',
              '--color-primary-600': '37 99 235',
              '--color-primary-700': '29 78 216',
              '--color-primary-800': '30 64 175',
              '--color-primary-900': '30 58 138',
              '--color-secondary-50': '245 243 255',
              '--color-secondary-100': '237 233 254',
              '--color-secondary-200': '221 214 254',
              '--color-secondary-300': '196 181 253',
              '--color-secondary-400': '167 139 250',
              '--color-secondary-500': '139 92 246',
              '--color-secondary-600': '124 58 237',
              '--color-secondary-700': '109 40 217',
              '--color-secondary-800': '91 33 182',
              '--color-secondary-900': '76 29 149',
              '--color-surface-50': '15 17 25',
              '--color-surface-100': '17 19 29',
              '--color-surface-200': '20 23 35',
              '--color-surface-300': '31 35 51',
              '--color-surface-400': '44 50 73',
              '--color-surface-500': '61 69 96',
              '--color-surface-600': '89 96 120',
              '--color-surface-700': '126 132 154',
              '--color-surface-800': '170 173 190',
              '--color-surface-900': '210 212 222'
            }
          }
        }
      }
    })
  ]
};
