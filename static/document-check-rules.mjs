export function fileKey(file) {
  return `${file.name}__${file.size}__${file.lastModified}`;
}

export function unavailableMessage(kind) {
  const detail = {
    proof_address: 'votre justificatif de domicile a moins de 3 mois',
    identity: 'votre pièce d’identité est bien lisible',
    host_identity: 'la pièce d’identité de la personne qui vous héberge est bien lisible',
    identity_photo: 'votre photo d’identité respecte tous les critères indiqués ci-dessus',
    hosting_certificate: 'l’attestation d’hébergement est bien signée par la personne qui vous héberge',
  }[kind] || 'votre pièce d’identité est bien lisible';
  return "La vérification automatique n'a pas pu aboutir. Veuillez vérifier que " + detail + '.';
}

export const checkPresentation = {
  proof_address: { label: 'Votre justificatif de domicile', pending: 'Un instant, je vérifie votre justificatif de domicile…',
    steps: ['Lecture de la date du document', 'Vérification du délai de 3 mois', 'Préparation de votre résultat'] },
  identity: { label: 'Votre pièce d’identité', pending: 'Un instant, je vérifie la lisibilité de votre pièce d’identité…',
    steps: ['Netteté et petits caractères', 'Cadrage, reflets et contraste', 'Vérification de chaque page fournie'] },
  host_identity: { label: 'La pièce d’identité de votre hébergeant', pending: 'Un instant, je vérifie la lisibilité de la pièce d’identité de la personne qui vous héberge…',
    steps: ['Netteté et petits caractères', 'Cadrage, reflets et contraste', 'Vérification de chaque page fournie'] },
  identity_photo: { label: 'Votre photo d’identité', pending: 'Un instant, je vérifie les critères visuels de votre photo d’identité…',
    steps: ['Netteté, éclairage et fond', 'Visage de face et bien dégagé', 'Expression et cadrage du portrait'] },
  hosting_certificate: { label: 'Votre attestation d’hébergement', pending: 'Un instant, je vérifie la présence d’une signature sur votre attestation d’hébergement…',
    steps: ['Lecture de l’attestation', 'Recherche de la signature de l’hébergeant', 'Vérification de chaque page fournie'] },
};
