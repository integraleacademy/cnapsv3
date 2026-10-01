export function fileKey(file) {
  return `${file.name}__${file.size}__${file.lastModified}`;
}

export function unavailableMessage(kind) {
  return kind === 'proof_address'
    ? "La vérification automatique n'a pas pu aboutir. Veuillez vérifier que votre justificatif de domicile a moins de 3 mois."
    : "La vérification automatique n'a pas pu aboutir. Veuillez vérifier que votre pièce d’identité est bien lisible.";
}
