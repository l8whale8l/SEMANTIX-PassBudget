// CesiumJS reads this global to resolve its Workers and bundled assets. It is set in index.html
// before any module loads (see the inline script there), pointing at public/cesium/.
declare global {
  interface Window {
    CESIUM_BASE_URL?: string
  }
}

export {}
