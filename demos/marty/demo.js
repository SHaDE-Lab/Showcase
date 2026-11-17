(function () {
  "use strict";
  const BASE = document.currentScript.src.replace(/[^/]*$/, "");
  window.UHDemos = window.UHDemos || {};
  window.UHDemos.marty = {
    async mount(el) {
      try {
        const [{ createViewer }, { buildMarty }] = await Promise.all([import(BASE + "../_3d/scene.js"), import(BASE + "../_3d/marty.js")]);
        el.viewer = createViewer(el, { label: "Interactive 3D model of the MaRTy cart", build: buildMarty, camera: { pos: [2.8, 1.65, 3.4], target: [0.05, 0.86, 0], min: 1.0, max: 7, fov: 32 }, ground: 1.75 });
      } catch (e) {
        el.innerHTML = '<p class="demo-status">The 3D model could not load (' + (e && e.message ? e.message : e) + "). It needs a modern browser and an internet connection for the 3D library.</p>";
      }
    },
  };
})();
