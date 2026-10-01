// Combines only non-identifying observations, across PDF pages AND selected files.
// It does not compare faces, names or document numbers and never changes admin status.
export function identityCompleteness(results, { partial = false } = {}) {
  if (!results.length) return null;
  if (results.some(result => !result)) return { status: 'pending', title: 'Vérification des faces en cours', message: 'Je vérifie le type de pièce et les faces présentes dans vos fichiers…' };
  if (results.some(result => result.status === 'warning')) return { status: 'warning', title: 'Pièce d’identité à corriger', message: 'Un fichier présente un problème. Consultez les alertes ci-dessous et remplacez-le par une version nette, complète et sans reflet.' };
  if (results.some(result => result.status !== 'success')) return { status: 'unknown', title: 'Pièce d’identité à vérifier', message: 'La vérification n’a pas pu être confirmée. Vérifiez la lisibilité et, pour une carte d’identité ou un titre de séjour, la présence du recto et du verso.' };
  const evidence = results.flatMap(result => Array.isArray(result.identity_evidence) ? result.identity_evidence : []);
  const known = evidence.filter(item => item?.confidence === 'high' && Array.isArray(item.sides));
  if (known.some(item => item.type === 'passport' && item.sides.includes('passport_biodata'))) {
    return { status: 'success', title: 'Passeport : c’est bon !', message: 'La page d’identité avec la photo est présente et lisible. Aucun verso n’est nécessaire.' };
  }
  for (const type of ['identity_card', 'residence_permit']) {
    const sides = new Set(known.filter(item => item.type === type).flatMap(item => item.sides));
    if (sides.has('front') && sides.has('back')) return { status: 'success', title: 'Recto et verso vérifiés', message: 'Les deux faces sont présentes et lisibles dans les fichiers sélectionnés.' };
  }
  if (partial) return { status: 'info', title: 'Fichier de remplacement vérifié', message: 'Ce contrôle porte sur les nouveaux fichiers sélectionnés. Pour une carte d’identité ou un titre de séjour, vérifiez que votre dossier contient bien les deux faces, y compris les documents déjà transmis.' };
  for (const type of ['identity_card', 'residence_permit']) {
    const sides = new Set(known.filter(item => item.type === type).flatMap(item => item.sides));
    if (sides.has('front') || sides.has('back')) {
      const missing = sides.has('front') ? 'verso' : 'recto';
      return { status: 'warning', title: `${missing === 'verso' ? 'Verso' : 'Recto'} manquant`, message: `Ajoutez le ${missing} de cette même ${type === 'identity_card' ? 'carte d’identité' : 'pièce de séjour'}. Vous pouvez déposer les deux faces dans un seul PDF ou dans deux fichiers séparés. Deux copies de la même face ne suffisent pas.`, missing };
    }
  }
  return { status: 'unknown', title: 'Faces de la pièce à vérifier', message: 'Je n’ai pas pu identifier avec certitude les faces nécessaires. Carte d’identité ou titre de séjour : recto et verso. Passeport : page d’identité avec la photo.' };
}
