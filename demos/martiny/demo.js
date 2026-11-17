(function () {
  "use strict";
  const BASE = document.currentScript.src.replace(/[^/]*$/, "");
  window.UHDemos = window.UHDemos || {};
  window.UHDemos.martiny = {
    async mount(el) {
      try {
        const [{ createViewer }, { buildMartiny }] = await Promise.all([import(BASE + "../_3d/scene.js"), import(BASE + "../_3d/martiny.js")]);
        el.viewer = createViewer(el, { label: "Interactive 3D model of the MaRTiny sensor", build: buildMartiny, camera: { pos: [0.62, 0.62, 0.78], target: [0, 0.31, 0], min: 0.3, max: 2.2, fov: 32 }, ground: 0.55 });
      } catch (e) {
        el.innerHTML = '<p class="demo-status">The 3D model could not load (' + (e && e.message ? e.message : e) + "). It needs a modern browser and an internet connection for the 3D library.</p>";
      }
    },
  };
})();
