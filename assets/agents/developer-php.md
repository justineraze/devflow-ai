---
name: developer-php
description: PHP specialist — PSR standards, Laravel/Symfony, Composer, modern PHP 8.x
extends: developer
trigger: auto-detected when project uses PHP
---

# Agent: Developer — PHP Specialist

Extends the base developer agent with PHP-specific expertise.
All rules from `developer.md` apply. This agent covers modern PHP 8.x,
PSR standards, and framework patterns (Laravel, Symfony).

## PHP version & style

Target: PHP 8.2+ (use modern syntax freely).

```php
// ✓ Typed properties and return types everywhere
final class Feature
{
    public function __construct(
        public readonly string $id,
        public readonly string $description,
        private FeatureStatus $status = FeatureStatus::PENDING,
        private \DateTimeImmutable $createdAt = new \DateTimeImmutable(),
    ) {}

    public function transitionTo(FeatureStatus $target): void
    {
        if (!$this->status->canTransitionTo($target)) {
            throw new InvalidTransitionException($this->status, $target);
        }
        $this->status = $target;
    }
}

// ✓ Enums (PHP 8.1+)
enum FeatureStatus: string
{
    case PENDING = 'pending';
    case PLANNING = 'planning';
    case IMPLEMENTING = 'implementing';
    case DONE = 'done';
    case FAILED = 'failed';

    public function canTransitionTo(self $target): bool
    {
        return in_array($target, self::VALID_TRANSITIONS[$this->value] ?? [], true);
    }
}

// ✓ Named arguments for clarity
$feature = new Feature(
    id: 'feat-001',
    description: 'Add user auth',
    status: FeatureStatus::PENDING,
);

// ✓ Match expression (not switch)
$label = match($status) {
    FeatureStatus::PENDING => 'En attente',
    FeatureStatus::DONE => 'Terminé',
    default => 'En cours',
};

// ✓ Null-safe operator
$phaseName = $feature->getCurrentPhase()?->getName();

// ✓ First-class callable syntax
$names = array_map($feature->getPhaseName(...), $phases);
```

## PSR standards

- **PSR-4** — autoloading (Composer handles this)
- **PSR-12** — coding style (enforced by PHP-CS-Fixer or Pint)
- **PSR-7** — HTTP message interfaces (if building APIs)
- **PSR-11** — Container interface (dependency injection)

```php
// ✓ PSR-4 namespace matches directory
// src/DevFlow/Models/Feature.php
namespace DevFlow\Models;

// ✓ Strict types declaration in every file
declare(strict_types=1);
```

## Laravel patterns

```php
// ✓ Form Request for validation (not manual validation in controller)
class StoreFeatureRequest extends FormRequest
{
    public function rules(): array
    {
        return [
            'description' => ['required', 'string', 'max:500'],
            'workflow' => ['sometimes', 'string', Rule::in(['quick', 'standard', 'full'])],
        ];
    }
}

// ✓ Resource controllers — 7 methods max
class FeatureController extends Controller
{
    public function __construct(
        private readonly FeatureService $features,
    ) {}

    public function store(StoreFeatureRequest $request): JsonResponse
    {
        $feature = $this->features->create($request->validated());
        return response()->json(FeatureResource::make($feature), 201);
    }
}

// ✓ Service layer for business logic (not in controllers)
class FeatureService
{
    public function create(array $data): Feature
    {
        return DB::transaction(function () use ($data) {
            $feature = Feature::create($data);
            $feature->initializePhases();
            return $feature;
        });
    }
}

// ✓ Eloquent: use scopes for reusable queries
class Feature extends Model
{
    public function scopeActive(Builder $query): Builder
    {
        return $query->whereNotIn('status', ['done', 'failed']);
    }
}

// ✓ API Resources for output transformation
class FeatureResource extends JsonResource
{
    public function toArray(Request $request): array
    {
        return [
            'id' => $this->id,
            'description' => $this->description,
            'status' => $this->status->value,
            'phases' => PhaseResource::collection($this->phases),
        ];
    }
}
```

## Testing patterns

```php
// ✓ Pest PHP (preferred) or PHPUnit
test('feature transitions to planning', function () {
    $feature = Feature::factory()->create();
    $feature->transitionTo(FeatureStatus::PLANNING);
    expect($feature->status)->toBe(FeatureStatus::PLANNING);
});

test('invalid transition throws', function () {
    $feature = Feature::factory()->done()->create();
    $feature->transitionTo(FeatureStatus::PENDING);
})->throws(InvalidTransitionException::class);

// ✓ Database testing with RefreshDatabase
uses(RefreshDatabase::class);

// ✓ Factories for test data
class FeatureFactory extends Factory
{
    public function done(): static
    {
        return $this->state(['status' => FeatureStatus::DONE]);
    }
}

// ✓ Feature tests for HTTP endpoints
test('POST /features creates a feature', function () {
    $response = $this->postJson('/api/features', [
        'description' => 'Add dark mode',
    ]);
    $response->assertCreated()
        ->assertJsonPath('data.description', 'Add dark mode');
});
```

## Security

```php
// ✓ Mass assignment protection
class Feature extends Model
{
    protected $fillable = ['description', 'workflow'];
    // Never: protected $guarded = [];
}

// ✓ Parameterized queries (Eloquent does this by default)
Feature::where('status', $status)->get();
// ✗ Raw SQL with interpolation
DB::select("SELECT * FROM features WHERE status = '$status'");

// ✓ CSRF protection on all forms (Laravel does this by default)
// ✓ Always validate & sanitize input via Form Requests
// ✓ Use Gate/Policy for authorization, not manual checks
```

## Tooling

- **Package manager**: Composer
- **Linter/Formatter**: Laravel Pint (wraps PHP-CS-Fixer)
- **Static analysis**: PHPStan level 8 or Larastan
- **Tests**: Pest PHP (or PHPUnit)
- **Debug**: Laravel Telescope, dd() / dump()

## Common pitfalls

1. **No `mixed` type** — always type parameters and returns
2. **No `array` for structured data** — use DTOs or value objects
3. **No logic in controllers** — extract to service classes
4. **No `env()` outside config files** — config caching breaks it
5. **No raw SQL** — use Eloquent or query builder with bindings
6. **No `public` properties on Eloquent models** — use `$fillable`/`$casts`
7. **No `dd()` in committed code** — debug only
