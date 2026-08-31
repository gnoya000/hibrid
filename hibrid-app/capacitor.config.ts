import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "app.lovable.hibrid",
  appName: "hibrid",
  webDir: "dist",
  ios: {
    contentInset: "always",
  },
  server: {
    // Punta alla preview Lovable: l'app iOS carica sempre l'ultima versione.
    url: "https://id-preview--6874be7f-bfb5-4e6b-9a3c-593d61f22333.lovable.app",
    cleartext: false,
  },
};

export default config;
