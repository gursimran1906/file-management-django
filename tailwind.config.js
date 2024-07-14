/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./templates/**/*.html',
  './frontend/**/*.html',
  './node_modules/flowbite/**/*.js'],
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
    require('flowbite/plugin')
  ]
  }
}
