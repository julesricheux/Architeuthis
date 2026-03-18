window.dashExtensions = Object.assign({}, window.dashExtensions, {
    default: {
        function0: function(feature, latlng) {
                const size = feature.properties.size || 0;
                const color = feature.properties.color || "#ff0000";
                const angle = feature.properties.angle || 0;
                const opacity = feature.properties.opacity || 0.80;
                const icon = feature.properties.icon || "material-symbols:circle";
                const html = `<span class="iconify"
        data-icon=${icon}
        data-width="${size}"
        data-height="${size}"
        style="
        transform: rotate(${angle}deg);
        color: ${color};
        display: block;
        opacity: ${opacity};
        ">
    </span>`;
                return L.marker(latlng, {
                    icon: L.divIcon({
                        html: html,
                        className: "",
                        iconSize: [size, size],
                        iconAnchor: [size / 2, size / 2]
                    })
                });
            }

            ,
        function1: function(feature) {
            if (feature.properties.kind === "route") {
                return {
                    color: feature.properties.color || "#ff0000",
                    weight: feature.properties.weight || 2,
                    opacity: feature.properties.opacity || 0.80,
                };
            }
            return {};
        }

    }
});