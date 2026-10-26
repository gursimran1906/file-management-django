/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./templates/**/*.html',
  './frontend/**/*.html',
  './users/**/*.html',
  './backend/**/*.html',
  './node_modules/flowbite/**/*.js'],
  // Risk scoring classes are chosen by a template filter and by
  // static/js/risk-assessment.js, so they never appear in a scanned template.
  // They are defined in static/src/input.css.
  safelist: [
    'risk-bar-low',
    'risk-bar-medium',
    'risk-bar-high',
    'risk-bar-none',
    'risk-question-risky',
  ],
  theme: {
    extend: {
      width: {
        'vw-64': 'calc(100vw - 256px)'
      },
      height: {
        '1/4-screen': '25vh',
      },
      transitionProperty: {
        'height': 'height'
      },
      
  },
  plugins: [
    require('flowbite/plugin'),
  ]
  }
}
