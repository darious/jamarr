const params = { name: "100% Hits" };
try {
    console.log("Input:", params.name);
    const name = decodeURIComponent(params.name);
    console.log("Decoded:", name);
} catch (e) {
    console.error("Error:", e.message);
}

const params2 = { name: "Normal Artist" };
try {
    console.log("Input:", params2.name);
    const name2 = decodeURIComponent(params2.name);
    console.log("Decoded:", name2);
} catch (e) {
    console.error("Error:", e.message);
}
