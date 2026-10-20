"use strict";
if (window.opener) window.opener.postMessage({kind: "hubzoid-oauth", query: location.search}, location.origin);
window.close();
