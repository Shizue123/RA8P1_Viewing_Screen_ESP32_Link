(() => {
  const authView = document.getElementById("authView");
  const canvas = document.getElementById("authCanvas");
  const scene = document.getElementById("authScene");
  const object = document.getElementById("authObject");
  const panel = document.querySelector(".auth-panel");
  if (!authView || !canvas || !scene || !object || !panel) return;

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const saveData = Boolean(navigator.connection?.saveData);
  const lowPower = (navigator.hardwareConcurrency || 4) <= 2;
  const allowAmbientMotion = !reducedMotion && !saveData && !lowPower;
  const gsap = window.gsap;

  function drawAmbient() {
    const context = canvas.getContext("2d", { alpha: true });
    if (!context) return;

    let width = 0;
    let height = 0;
    let frameHandle = 0;
    let particles = [];
    const pointer = { x: .5, y: .5 };

    function resize() {
      const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      const count = width < 820 ? 10 : 22;
      particles = Array.from({ length: count }, (_, index) => ({
        x: Math.random() * width,
        y: Math.random() * height,
        z: .2 + Math.random() * .8,
        radius: index % 7 === 0 ? 2.1 : .7 + Math.random() * 1.1,
      }));
      render();
    }

    function render() {
      context.clearRect(0, 0, width, height);
      particles.forEach((particle, index) => {
        const shiftX = (pointer.x - .5) * 18 * particle.z;
        const shiftY = (pointer.y - .5) * 12 * particle.z;
        context.beginPath();
        context.fillStyle = index % 7 === 0
          ? `rgba(233, 99, 59, ${.16 + particle.z * .16})`
          : `rgba(48, 75, 65, ${.07 + particle.z * .12})`;
        context.arc(particle.x + shiftX, particle.y + shiftY, particle.radius * particle.z, 0, Math.PI * 2);
        context.fill();
      });
      frameHandle = 0;
    }

    function scheduleRender() {
      if (frameHandle || authView.hidden || document.visibilityState !== "visible") return;
      frameHandle = requestAnimationFrame(render);
    }

    window.addEventListener("resize", resize, { passive: true });
    window.addEventListener("pointermove", (event) => {
      pointer.x = event.clientX / Math.max(width, 1);
      pointer.y = event.clientY / Math.max(height, 1);
      scheduleRender();
    }, { passive: true });
    new MutationObserver(() => {
      if (!authView.hidden) scheduleRender();
    }).observe(authView, { attributes: true, attributeFilter: ["hidden"] });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && !authView.hidden) scheduleRender();
    });
    resize();
  }

  drawAmbient();
  if (!gsap || reducedMotion) return;

  gsap.timeline({ defaults: { ease: "power3.out" } })
    .from(".auth-panel", { autoAlpha: 0, y: 34, rotationX: -5, duration: .9 })
    .from(".auth-brand, .auth-heading, .remembered-accounts, .session-account, .auth-card", {
      autoAlpha: 0, y: 18, duration: .58, stagger: .08,
    }, "-=.55")
    .from(".slab-front", { autoAlpha: 0, z: -80, rotationZ: -8, duration: .85 }, .08)
    .from(".slab-mid", { autoAlpha: 0, x: -35, y: 28, rotationZ: -5, duration: .8 }, .18)
    .from(".slab-back", { autoAlpha: 0, x: 42, y: -20, rotationZ: 4, duration: .8 }, .24)
    .from(".scene-orbit, .scene-coordinate", { autoAlpha: 0, scale: .84, duration: .72, stagger: .07 }, .2);

  if (!allowAmbientMotion || window.innerWidth < 821) return;

  const sceneRotateY = gsap.quickTo(scene, "rotationY", { duration: .75, ease: "power3.out" });
  const sceneRotateX = gsap.quickTo(scene, "rotationX", { duration: .75, ease: "power3.out" });
  const panelRotateY = gsap.quickTo(panel, "rotationY", { duration: .8, ease: "power3.out" });
  const panelRotateX = gsap.quickTo(panel, "rotationX", { duration: .8, ease: "power3.out" });
  const objectX = gsap.quickTo(object, "x", { duration: .48, ease: "power2.out" });
  const objectY = gsap.quickTo(object, "y", { duration: .48, ease: "power2.out" });
  let pointerFrame = 0;
  let pendingPointer = null;

  function updateDepth() {
    pointerFrame = 0;
    if (!pendingPointer) return;
    const x = pendingPointer.x;
    const y = pendingPointer.y;
    sceneRotateY(x * 8);
    sceneRotateX(y * -6);
    panelRotateY(x * -2.8);
    panelRotateX(y * 2.2);
    objectX(x * 13);
    objectY(y * 10);
  }

  authView.addEventListener("pointermove", (event) => {
    pendingPointer = {
      x: event.clientX / window.innerWidth - .5,
      y: event.clientY / window.innerHeight - .5,
    };
    if (!pointerFrame) pointerFrame = requestAnimationFrame(updateDepth);
  }, { passive: true });

  authView.addEventListener("pointerleave", () => {
    sceneRotateY(0);
    sceneRotateX(0);
    panelRotateY(0);
    panelRotateX(0);
    objectX(0);
    objectY(0);
  });
})();
