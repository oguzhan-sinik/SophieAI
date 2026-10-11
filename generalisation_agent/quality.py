"""Human release gate; no model/provider calls, only aggregate results are released."""
from pathlib import Path
import json
from pydantic import Field, model_validator
from agent.builder.artifacts import digest, write_json
from .config import ROOT, confined
from .models import Record


class Rating(Record):
    reviewer: str = Field(min_length=1)
    plausible: bool
    responsive: bool
    facts_correct: bool
    consent_correct: bool
    comment: str = ''


class Sample(Record):
    recording: str
    sha256: str
    profile: str = Field(pattern=r'^(baseline|ordinary|stress)$')
    backend: str = Field(pattern=r'^(local_proxy|freya_chat_diagnostic|freya_persona_diagnostic)$')
    split: str = Field(pattern=r'^(development|holdout)$')
    ratings: list[Rating] = Field(min_length=2,max_length=2)


class Review(Record):
    samples: list[Sample] = Field(min_length=30,max_length=30)
    @model_validator(mode='after')
    def independent(self):
        reviewers = {r.reviewer for s in self.samples for r in s.ratings}
        if len(reviewers)!=2 or any(len({r.reviewer for r in s.ratings})!=2 for s in self.samples):
            raise ValueError('Two independent reviewers must rate every sample')
        if len({s.sha256 for s in self.samples})!=30:
            raise ValueError('Review requires thirty distinct synthetic recordings')
        if {s.profile for s in self.samples} != {'baseline','ordinary','stress'} or {s.split for s in self.samples} != {'development','holdout'}:
            raise ValueError('Review must cover all profiles and both pack splits')
        if not any(s.backend.startswith('freya_') for s in self.samples) or not any(s.backend=='local_proxy' for s in self.samples):
            raise ValueError('Review needs local and actual live backend evidence')
        return self


def review_quality(path):
    path = confined(path)
    if not path.is_relative_to(ROOT/'private'):
        raise ValueError('Human reviews and recording references must stay private')
    review = Review.model_validate_json(path.read_text())
    for sample in review.samples:
        recording = confined(sample.recording)
        if not recording.is_relative_to(ROOT/'private'):
            raise ValueError('Human review must reference private synthetic recordings')
        value = json.loads(recording.read_text())
        if digest(value)!=sample.sha256:
            raise ValueError('Reviewed recording changed after sampling')
        if value.get('backend') != sample.backend or value.get('profile') != sample.profile or value.get('split') != sample.split:
            raise ValueError('Human sample strata do not match the measured recording')
    plausible = sum(all(r.plausible for r in sample.ratings) for sample in review.samples)
    responsive = sum(all(r.responsive for r in sample.ratings) for sample in review.samples)
    violations = sum(any(not r.facts_correct or not r.consent_correct for r in s.ratings) for s in review.samples)
    result = {'samples':30,'reviewers':2,'plausibility_accepted':plausible,'responsiveness_accepted':responsive,
              'fidelity_or_consent_violations':violations,'accepted':plausible>=27 and responsive>=27 and violations==0,
              'review_sha256':digest(review.model_dump(mode='json'))}
    write_json(ROOT/'artifacts'/path.parent.name/'human_quality.json',result,immutable=True)
    return result


def save_sample(root, case_id, repetition, recording, profile, split, backend):
    """Individual immutable review input; no sampling/quarantining changes campaign denominators."""
    root = confined(root)
    if not root.is_relative_to(ROOT/'private'):
        raise ValueError('Review samples must stay private')
    if profile not in {'baseline','ordinary','stress'}:
        return None
    if not case_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in case_id):
        raise ValueError('Unsafe review sample case id')
    value = {**recording,'case_id':case_id,'repetition':repetition,'profile':profile,'split':split,'backend':backend}
    path = root/'review_samples'/f'{case_id}-{repetition}.json'
    write_json(path,value,immutable=True)
    return {'recording':str(path),'sha256':digest(value),'profile':profile,'split':split,'backend':backend}
