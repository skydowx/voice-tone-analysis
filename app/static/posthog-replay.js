(function initializePrivacyFirstReplay() {
  "use strict";

  const loaderTag = document.currentScript;
  const projectToken = loaderTag && loaderTag.dataset.posthogToken;
  const apiHost = loaderTag && loaderTag.dataset.posthogHost;
  if (!projectToken || !apiHost || window.posthog?.__SV) {
    return;
  }

  const posthog = (window.posthog = window.posthog || []);
  posthog._i = [];
  posthog.init = function init(token, config, name) {
    function queueMethod(target, method) {
      target[method] = function queuedMethod() {
        target.push([method].concat(Array.prototype.slice.call(arguments)));
      };
    }

    const script = document.createElement("script");
    script.type = "text/javascript";
    script.crossOrigin = "anonymous";
    script.async = true;
    script.src = `${config.api_host.replace(".i.posthog.com", "-assets.i.posthog.com")}/static/1/array.js`;
    document.head.appendChild(script);

    let instance = posthog;
    if (name !== undefined) {
      instance = posthog[name] = [];
    } else {
      name = "posthog";
    }
    instance.people = instance.people || [];
    [
      "capture",
      "opt_in_capturing",
      "opt_out_capturing",
      "has_opted_in_capturing",
      "has_opted_out_capturing",
      "reset",
      "startSessionRecording",
      "stopSessionRecording",
    ].forEach(function addQueue(method) {
      queueMethod(instance, method);
    });
    posthog._i.push([token, config, name]);
  };
  posthog.__SV = 1;

  posthog.init(projectToken, {
    api_host: apiHost,
    defaults: "2026-05-30",
    strict_script_versioning: true,
    autocapture: false,
    capture_pageview: false,
    capture_pageleave: false,
    capture_dead_clicks: false,
    capture_exceptions: false,
    capture_heatmaps: false,
    capture_performance: false,
    disable_surveys: true,
    enable_recording_console_log: false,
    cross_subdomain_cookie: false,
    persistence: "sessionStorage",
    person_profiles: "identified_only",
    respect_dnt: true,
    session_recording: {
      maskAllInputs: false,
      maskInputOptions: {
        password: true,
      },
      maskCapturedNetworkRequestFn: function redactUrl(request) {
        if (request.name) {
          request.name = request.name.split("?")[0];
        }
        return request;
      },
    },
  });
  posthog.startSessionRecording();
})();
