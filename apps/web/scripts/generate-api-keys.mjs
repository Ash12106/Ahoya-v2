import { generateKeyPairSync, randomBytes } from "node:crypto";

const keyId = `api-${randomBytes(6).toString("hex")}`;
const { privateKey, publicKey } = generateKeyPairSync("ed25519", {
  privateKeyEncoding: { format: "der", type: "pkcs8" },
  publicKeyEncoding: { format: "der", type: "spki" },
});

console.log(`API_ASSERTION_KEY_ID=${keyId}`);
console.log(`API_ASSERTION_PRIVATE_KEY=${privateKey.toString("base64")}`);
console.log(`WEB_ASSERTION_PUBLIC_KEYS={"${keyId}":"${publicKey.toString("base64")}"}`);
