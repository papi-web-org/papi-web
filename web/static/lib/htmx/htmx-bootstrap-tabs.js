/* https://marcus-obst.de/blog/use-bootstrap-5x-tabs-with-htmx */
(function(){
    htmx.defineExtension('bs-tabs', {
        onEvent: function (name, evt) {
            //  // before a request is made,
            //  // check if there the content was already loaded into the tab pane
            //  if (name === "htmx:beforeRequest") {
            //    if(evt.detail.target.hasChildNodes()){
            //        // stop request
            //        return false;
            //    }
            //}
            if (name === "htmx:afterProcessNode") {
                let allLinks = htmx.findAll(htmx.find('[hx-ext="bs-tabs"]'), '.nav-link');
                // loop through all .nav-links
                allLinks.forEach(triggerEl => {
                    // if the bootstrap data attribute for the target pane is missing...
                    if(!triggerEl.hasAttribute('data-bs-target')){
                        // ... add it. It's the same as the hx-target attribute.
                        triggerEl.setAttribute('data-bs-target', triggerEl.getAttribute('hx-target'));
                    }
                    // add the attribute that tells initializes the bootstrap functionality
                    triggerEl.setAttribute('data-bs-toggle', 'tab');
                });
            }
            return true;
        }
    });
})();
